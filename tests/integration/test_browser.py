"""Real HTTP/Store/Git/process browser contracts, with a fixture Serve boundary."""
import asyncio
from hashlib import sha256
import re
import unittest
from urllib.parse import urlencode
from uuid import uuid4
from cursus.http import LocalConnection
from tests.support import SocketService
from tests.phase_support import phase_runtime, drive

ORIGIN = 'https://cursus.fixture.ts.net'
LOGIN = 'operator@fixture.invalid'


class BrowserWire:
    def __init__(self, path):
        self.path, self.cookie = str(path), ''

    def connection(self, headers=None):
        base = {'Host': 'cursus.fixture.ts.net', 'Tailscale-User-Login': LOGIN}
        if self.cookie:
            base['Cookie'] = self.cookie
        base.update(headers or {})
        return LocalConnection(self.path), base

    async def request(self, path='/', data=None, headers=None):
        def send():
            connection, base = self.connection(headers)
            try:
                if data is not None:
                    base.setdefault('Origin', ORIGIN)
                    base.setdefault('Content-Type', 'application/x-www-form-urlencoded')
                connection.request('POST' if data is not None else 'GET', path,
                                   urlencode(data) if data is not None else None, base)
                response = connection.getresponse()
                raw = response.read()
                cookie = response.getheader('Set-Cookie')
                if cookie:
                    self.cookie = cookie.split(';')[0]
                return response.status, dict(response.getheaders()), raw
            finally:
                connection.close()
        return await asyncio.to_thread(send)

    async def token(self):
        status, headers, raw = await self.request('/?new=1')
        if status != 200:
            raise AssertionError(raw)
        return re.search(rb'name="csrf" value="([^"]+)"', raw)[1].decode()

    async def event(self, path, headers=None):
        def read():
            connection, base = self.connection(headers)
            try:
                connection.request('GET', path, headers=base)
                response = connection.getresponse()
                lines = []
                for _ in range(10):
                    line = response.readline()
                    lines.append(line)
                    if line == b'\n':
                        return response.status, b''.join(lines)
                raise AssertionError('No bounded SSE frame')
            finally:
                connection.close()
        return await asyncio.to_thread(read)


class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def open(self, rt):
        rt['config']['service'].update(external_origin=ORIGIN, operator_login=LOGIN)
        service = SocketService(rt['control'], rt['ws'].root/'browser.sock', local=False, browser=True)
        await service.__aenter__()
        wire = BrowserWire(rt['ws'].root/'browser.sock')
        wire.service = service
        self.addAsyncCleanup(self._close, wire, rt)
        return wire

    async def test_serve_identity_csrf_origin_static_and_submission(self):
        async with phase_runtime() as rt:
            wire = await self.open(rt)
            token = await wire.token()
            status, headers, raw = await wire.request()
            self.assertEqual(status, 200)
            self.assertIn(b'Follow OS', raw)
            self.assertIn(b'unknown', raw)
            self.assertIn('HttpOnly', headers['set-cookie'])
            self.assertIn('Secure', headers['set-cookie'])
            self.assertIn('SameSite=strict', headers['set-cookie'])
            self.assertIn("script-src 'self'", headers['content-security-policy'])
            for override in ({'Tailscale-User-Login':''}, {'Tailscale-User-Login':'wrong'},
                             {'Host':'evil.invalid'}, {'Tailscale-User-Login':'','Authorization':'Bearer fixture-bearer'}):
                self.assertEqual((await wire.request(headers=override))[0], 403)
            # Duplicate identity is rejected even when both supplied values match.
            def duplicate():
                connection = LocalConnection(wire.path)
                try:
                    connection.putrequest('GET','/',skip_host=True)
                    connection.putheader('Host','cursus.fixture.ts.net')
                    connection.putheader('Tailscale-User-Login',LOGIN)
                    connection.putheader('Tailscale-User-Login',LOGIN)
                    connection.endheaders()
                    response = connection.getresponse()
                    response.read()
                    return response.status
                finally:
                    connection.close()
            self.assertEqual(await asyncio.to_thread(duplicate),403)
            form = dict(kind='submit', csrf=token, request_id=str(uuid4()), workflow='code',form='one-shot',
                source_kind='inline',text='<script>alert(1)</script> implement change',
                repository='fixture|repo|refs/heads/main')
            self.assertEqual((await wire.request('/operator/actions',form,{'Origin':'https://evil.invalid'}))[0],403)
            self.assertEqual((await wire.request('/operator/actions',dict(form,csrf='wrong')))[0],403)
            status, headers, _ = await wire.request('/operator/actions',form)
            self.assertEqual(status,303)
            location = headers['location']
            self.assertEqual((await wire.request('/operator/actions',form))[1]['location'],location)
            self.assertEqual(len((await rt['db'].store.read('phases'))['items']),2)
            self.assertEqual((await wire.request(location))[0],200)
            self.assertEqual((await wire.request('/operator/actions',dict(form,text='changed')))[0],409)
            self.assertEqual((await wire.request('/static/htmx.min.js'))[0],200)
            self.assertEqual((await wire.request('/static/events.js'))[0],200)
            await self._close(wire, rt)

    async def _close(self, wire, rt):
        # Close while the fixture root still exists, before its outer cleanup.
        service = wire.service
        wire.service = None
        if service is not None:
            await service.__aexit__(None,None,None)

    async def test_sse_committed_cursor_replay_and_reset(self):
        async with phase_runtime() as rt:
            wire = await self.open(rt)
            try:
                path = '/phases/' + rt['phase_id'] + '/events'
                status, first = await wire.event(path)
                self.assertEqual(status,200)
                cursor = int(re.search(rb'id: (\d+)',first)[1])
                _, second = await wire.event(path, {'Last-Event-ID':str(cursor)})
                self.assertGreater(int(re.search(rb'id: (\d+)',second)[1]),cursor)
                _, reset = await wire.event(path+'?cursor=999999999')
                self.assertIn(b'event: reset',reset)
                self.assertEqual((await wire.request(path+'?cursor=invalid'))[0],422)
                self.assertEqual((await wire.request(path,headers={'Tailscale-User-Login':'wrong'}))[0],403)
                # >100 committed events must not skip to the global high water.
                claim = await rt['runner'].claim('repository')
                for i in range(105):
                    await rt['runner'].event(claim['attempt_id'],'log',{'stream':'stdout','text':f'line {i}'})
                await rt['runner'].replay()
                page = await rt['control'].query('local_operator','events',rt['phase_id'],0)
                self.assertEqual(len(page['items']),100)
                self.assertLess(page['cursor'],page['snapshot_cursor'])
                next_page = await rt['control'].query('local_operator','events',rt['phase_id'],page['cursor'])
                self.assertTrue(next_page['items'])
                self.assertGreater(next_page['items'][0]['cursor'],page['cursor'])
            finally:
                await self._close(wire,rt)

    async def test_pipeline_download_cancel_and_escaped_events(self):
        async with phase_runtime() as rt:
            phase = await drive(rt)
            wire = await self.open(rt)
            try:
                status, _, raw = await wire.request('/phases/'+rt['phase_id'])
                self.assertEqual(status,200)
                self.assertIn(b'Open PR on GitHub',raw)
                self.assertIn(b'Merging is your action',raw)
                ref=phase['evidence'][0]['log']
                status, headers, raw = await wire.request('/artifacts/'+ref['id'])
                self.assertEqual(status,200)
                self.assertEqual(sha256(raw).hexdigest(),ref['digest'])
                self.assertIn('attachment',headers['content-disposition'])
                self.assertEqual((await wire.request('/artifacts/'+ref['id'],headers={'Tailscale-User-Login':'wrong'}))[0],403)
                attempts=(await rt['db'].store.read('attempts'))['items']
                self.assertEqual((await wire.request('/attempts/'+attempts[0]['id']))[0],200)
                token=await wire.token()
                form=dict(kind='cancel',csrf=token,request_id=str(uuid4()),phase_id=rt['phase_id'])
                self.assertEqual((await wire.request('/operator/actions',form))[0],409)
            finally:
                await self._close(wire,rt)

    async def test_guided_answer_and_original_attempt_commands(self):
        from tests.support import code_input
        from tests.integration.test_interview_debate import conversation_binaries
        from tests.phase_support import phase_state
        value=code_input(); value['source']={'kind':'interview'}
        async with phase_runtime(value=value) as rt:
            conversation_binaries(rt)
            phase=await drive(rt,lambda p:bool(p.get('questions')))
            wire=await self.open(rt)
            try:
                token=await wire.token()
                path='/phases/'+rt['phase_id']
                question=phase['questions'][0]
                self.assertIn(question['text'].encode(),(await wire.request(path))[2])
                form=dict(kind='answer',csrf=token,request_id=str(uuid4()),phase_id=rt['phase_id'],
                          question_id=question['id'],text='Working output for engineers.')
                self.assertEqual((await wire.request('/operator/actions',form))[0],303)
                self.assertEqual((await wire.request('/operator/actions',form))[0],303)
                self.assertEqual((await wire.request('/operator/actions',dict(form,request_id=str(uuid4()))))[0],409)
                await drive(rt,lambda p:p['state']=='execution')
                claim=await rt['runner'].claim('worker')
                attempt_id=claim['attempt_id']
                await rt['runner'].event(attempt_id,'log',{'stream':'system','text':'<script>bad()</script>\x1b[31m'})
                await rt['runner'].event(attempt_id,'usage',{'input_tokens':1234,'output_tokens':567,'currency':'USD','cost':'0.12'})
                await rt['runner'].replay()
                raw=(await wire.request('/attempts/'+attempt_id))[2]
                self.assertIn(b'1234 in / 567 out',raw)
                self.assertIn(b'USD 0.12',raw)
                self.assertNotIn(b'<script>bad()',raw)
                self.assertIn(b'\\u003cscript\\u003e',raw)
                steer=dict(kind='steer',csrf=token,request_id=str(uuid4()),attempt_id=attempt_id,text='Keep the invariant.')
                self.assertEqual((await wire.request('/operator/actions',steer))[0],303)
                attempt=(await rt['control'].query('local_operator','attempts',attempt_id))['items'][0]
                self.assertEqual(next(iter(attempt['commands'].values()))['state'],'pending')
                cancel=dict(kind='cancel',csrf=token,request_id=str(uuid4()),phase_id=rt['phase_id'])
                self.assertEqual((await wire.request('/operator/actions',cancel))[0],303)
                self.assertEqual((await phase_state(rt))['state'],'canceling')
                directive=await rt['runner'].reconcile()
                await rt['runner'].apply_commands(directive['commands'])
                self.assertEqual((await phase_state(rt))['state'],'canceled')
            finally:
                await self._close(wire,rt)

    async def test_unknown_ownership_and_reasoned_abandonment(self):
        from tests.phase_support import phase_state
        async with phase_runtime() as rt:
            claim=await rt['runner'].claim('repository')
            wire=await self.open(rt)
            try:
                token=await wire.token()
                form=dict(kind='declare_unrecoverable',csrf=token,request_id=str(uuid4()),
                          attempt_id=claim['attempt_id'],reason='Permanent loss evidence from operator.')
                self.assertEqual((await wire.request('/operator/actions',form))[0],303)
                raw=(await wire.request('/attempts/'+claim['attempt_id']))[2]
                self.assertIn(b'ownership held',raw)
                self.assertIn(b'Abandon attempt',raw)
                abandon=dict(kind='abandon',csrf=token,request_id=str(uuid4()),attempt_id=claim['attempt_id'],reason='')
                self.assertEqual((await wire.request('/operator/actions',abandon))[0],422)
                abandon.update(reason='Isolated the lost execution.',request_id=str(uuid4()))
                self.assertEqual((await wire.request('/operator/actions',abandon))[0],303)
                row=(await rt['control'].query('local_operator','attempts',claim['attempt_id']))['items'][0]
                self.assertEqual(row['status'],'abandoned')
                self.assertEqual((await phase_state(rt))['state'],'execution')
            finally:
                await self._close(wire,rt)
