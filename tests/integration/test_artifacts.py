"""Artifact state is produced by the real intake/Git/verifier/upload path."""
import asyncio
from hashlib import sha256
import unittest
from uuid import uuid4
from cursus.contracts import Problem, canonical_json
from cursus.artifact_control import download
from cursus.http import LocalConnection
from cursus.runner import Journal
from tests.phase_support import phase_runtime, drive


class ArtifactTests(unittest.IsolatedAsyncioTestCase):
    async def test_verifier_file_delivery_replay_and_entitlement(self):
        async with phase_runtime() as rt:
            phase = await drive(rt)
            self.assertEqual(phase['state'], 'delivered', phase.get('reason'))
            ref = phase['evidence'][0]['log']
            rows = (await rt['db'].store.read('artifacts'))['items']
            row = next(r for r in rows if r['id'] == ref['id'])
            self.assertEqual(row['state'], 'ready')
            def fetch():
                connection = LocalConnection(str(rt['ws'].root/'operator.sock'))
                try:
                    connection.request('GET', '/artifacts/' + ref['id'])
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertTrue(response.getheader('Content-Disposition').startswith('attachment;'))
                    return response.read()
                finally:
                    connection.close()
            raw = await asyncio.to_thread(fetch)
            self.assertEqual(sha256(raw).hexdigest(), ref['digest'])
            self.assertEqual(len(raw), ref['length'])
            with self.assertRaises(Problem):
                await download(rt['control'], 'wrong-principal', ref['id'])
            with self.assertRaises(Problem):
                await rt['runner'].transport.binary('runner/artifacts/' + ref['id'] + '?claim_id=' + str(uuid4()))
            before = len(rows)
            await rt['runner'].replay()
            self.assertEqual(len((await rt['db'].store.read('artifacts'))['items']), before)

    async def test_interrupted_upload_and_lost_receipt_recover_without_reexecution(self):
        async with phase_runtime() as rt:
            await drive(rt, lambda p: p['state'] == 'verification')
            claim = await rt['runner'].claim('verifier')
            self.assertIsNotNone(claim)
            transport = rt['runner'].transport
            original = transport.upload
            async def lost(attempt, ref, path):
                await original(attempt, ref, path)
                raise OSError('Lost upload response')
            transport.upload = lost
            with self.assertRaises(OSError):
                await rt['runner'].dispatch(claim)
            self.assertEqual((await rt['control'].query('local_operator', 'attempts', claim['attempt_id']))['items'][0]['status'], 'active')
            await rt['control'].action('local_operator',str(uuid4()),dict(kind='declare_unrecoverable',
                attempt_id=claim['attempt_id'],reason='Lost upload acknowledgment; outcome unknown.'))
            # Reopen the fsynced journal as after a runner restart, replay receipts
            # and finals; do not launch the verifier a second time.
            rt['journal'].close()
            reopened = Journal(rt['ws'].state)
            rt['runner'].journal = reopened
            rt['journal'] = reopened
            transport.upload = original
            try:
                await rt['runner'].reconcile()
                await rt['runner'].replay()
                attempt = (await rt['control'].query('local_operator', 'attempts', claim['attempt_id']))['items'][0]
                self.assertEqual(attempt['status'], 'terminal')
                self.assertEqual(sum(r['kind']=='launch' and r['value']==claim['attempt_id'] for r in reopened.records), 1)
            finally:
                reopened.close()

    async def test_mismatch_unsafe_names_limits_and_partial_bytes(self):
        async with phase_runtime() as rt:
            claim = await rt['runner'].claim('repository')
            wire = rt['runner'].transport
            from cursus.runner_files import headers
            ref = dict(id=str(uuid4()), digest=sha256(b'abc').hexdigest(), length=3,
                       name='evidence.txt', media_type='text/plain')
            route = f"attempts/{claim['attempt_id']}/artifacts/{ref['id']}"
            # A disconnected producer leaves staged metadata, never ready bytes.
            from cursus.artifact_control import upload
            async def interrupted():
                yield b'ab'
                raise OSError('Interrupted body stream')
            with self.assertRaises(OSError):
                await upload(rt['control'],rt['config']['runner']['id'],rt['journal'].generation,
                             claim['attempt_id'],ref,interrupted())
            with self.assertRaises(Problem):
                await download(rt['control'],'local_operator',ref['id'])
            # A digest mismatch cannot make the reservation ready.
            for raw in (b'bad',):
                h = headers(ref)
                h['Content-Length'] = str(len(raw))
                with self.assertRaises(Problem):
                    await wire.binary(route, raw, h)
            self.assertEqual(await wire.binary(route, b'abc', headers(ref)), ref)
            self.assertEqual(await wire.binary(route, b'abc', headers(ref)), ref)
            with self.assertRaises(Problem):
                await wire.binary(route, b'abc', headers(dict(ref, name='other.txt')))
            for name in ('../escape', 'a/b', 'a\\b', '..', 'x\nheader'):
                with self.assertRaises(Problem):
                    await wire.binary(route, b'abc', headers(dict(ref, name=name)))
            with self.assertRaises(Problem):
                await wire.binary(route, b'', headers(dict(ref, length=32*1024*1024+1)))
            with self.assertRaises(Problem):
                await wire.binary(f'attempts/{uuid4()}/artifacts/{uuid4()}', b'abc', headers(ref))
            self.assertEqual(list(rt['ws'].artifacts.glob('.upload-*')), [])

    async def test_abandoned_pending_upload_does_not_block_replay(self):
        async with phase_runtime() as rt:
            await drive(rt,lambda p:p['state']=='verification')
            claim=await rt['runner'].claim('verifier')
            original=rt['runner'].transport.upload
            async def unavailable(*args):
                raise OSError('Upload interrupted before response')
            rt['runner'].transport.upload=unavailable
            with self.assertRaises(OSError):
                await rt['runner'].dispatch(claim)
            for kind in ('declare_unrecoverable','abandon'):
                await rt['control'].action('local_operator',str(uuid4()),dict(kind=kind,
                    attempt_id=claim['attempt_id'],reason='Operator isolated lost verifier.'))
            self.assertTrue(any(r['kind']=='artifact_pending' for r in rt['journal'].records))
            self.assertTrue(list(rt['journal'].root.glob('evidence-*')))
            rt['runner'].transport.upload=original
            await rt['runner'].reconcile()
            await rt['runner'].replay()
            # Compaction retires the discarded upload's record and spool file together.
            self.assertFalse(any(r['kind']=='artifact_pending' for r in rt['journal'].records))
            self.assertFalse(list(rt['journal'].root.glob('evidence-*')))
            attempt=(await rt['control'].query('local_operator','attempts',claim['attempt_id']))['items'][0]
            self.assertEqual(attempt['status'],'abandoned')
            self.assertEqual((await drive(rt))['state'],'delivered')
