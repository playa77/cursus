"""Host-native lifecycle fixtures (ADR 0016).

These run local fixture processes. They establish bounded process lifecycle and
environment behavior only: no real CLI, login, provider call or isolation claim.
"""
import asyncio
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from uuid import uuid4
from cursus.contracts import Problem
from cursus.host import HostRuntime
from tests.support import workspace

CEILINGS = dict(worker=4, claude=2, codex=2, agy=2, verifier=1, repository=1)


def runtime(ws, name='runtime', **settings):
    values = dict(disk_reserve_mb=1, host_reserve_mb=1)
    values.update(settings)
    return HostRuntime(values, ws.state / name, CEILINGS)


def alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


async def launch(host, ws, lane='worker', cli='pi', argv=None, **kwargs):
    attempt = str(uuid4())
    assert await host.reserve(attempt, lane, cli)
    await host.prepare(attempt, ws.worktrees)
    token = host.current.set(attempt)
    try:
        process = await host.spawn(argv or [sys.executable, '-c', 'import time; time.sleep(60)'],
                                   ws.worktrees, stdin=asyncio.subprocess.PIPE,
                                   stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                   start_new_session=True, **kwargs)
    finally:
        host.current.reset(token)
    return attempt, process


class HostRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_ceilings_control_admission_without_credential_domains(self):
        with workspace() as ws:
            host = runtime(ws)
            for lane, cli, count in (('worker', 'pi', 4), ('claude', 'claude', 2),
                                     ('codex', 'codex', 2), ('agy', 'agy', 2)):
                for _ in range(count):
                    self.assertTrue(await host.reserve(str(uuid4()), lane, cli))
                self.assertFalse(await host.reserve(str(uuid4()), lane, cli))
            self.assertTrue(await host.reserve(str(uuid4()), 'verifier'))
            self.assertFalse(await host.reserve(str(uuid4()), 'verifier'))
            self.assertFalse(any('domain' in entry for entry in host.entries.values()))

    async def test_reservation_identity_is_never_reused(self):
        with workspace() as ws:
            host = runtime(ws)
            attempt = str(uuid4())
            self.assertTrue(await host.reserve(attempt, 'worker', 'pi'))
            with self.assertRaises(Problem):
                await host.reserve(attempt, 'worker', 'pi')

    async def test_actual_host_memory_and_disk_pressure_still_delay_starts(self):
        with workspace() as ws:
            host = runtime(ws, host_reserve_mb=1024)
            with patch.object(Path, 'read_text', return_value='MemAvailable: 1048576 kB\n'):
                self.assertFalse(host.fits('worker'))
            with patch.object(Path, 'read_text', return_value='MemAvailable: 1114112 kB\n'), \
                    patch('cursus.host.shutil.disk_usage', return_value=SimpleNamespace(free=10**9)):
                self.assertTrue(host.fits('worker'))
            with patch.object(Path, 'read_text', return_value='MemAvailable: 1114112 kB\n'), \
                    patch('cursus.host.shutil.disk_usage', return_value=SimpleNamespace(free=0)):
                self.assertFalse(host.fits('worker'))

    async def test_child_gets_only_the_allowlisted_environment_and_worktree_cwd(self):
        with workspace() as ws:
            host = runtime(ws, pass_env=['XDG_RUNTIME_DIR'])
            script = 'import json,os;print(json.dumps([dict(os.environ),os.getcwd()]))'
            with patch.dict(os.environ, {'CURSUS_PARENT_SECRET': 'must-not-reach-child',
                                         'XDG_RUNTIME_DIR': '/run/user/fixture', 'OTHER': 'x'}):
                attempt, process = await launch(host, ws, argv=[sys.executable, '-c', script])
            raw, _ = await process.communicate()
            environment, cwd = json.loads(raw)
            user = pwd.getpwuid(os.getuid())
            self.assertEqual(set(environment), {'PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'TMPDIR', 'XDG_RUNTIME_DIR'})
            self.assertEqual(environment['HOME'], user.pw_dir)  # The signed-in user's real HOME.
            self.assertEqual(environment['USER'], user.pw_name)
            self.assertEqual(environment['XDG_RUNTIME_DIR'], '/run/user/fixture')
            self.assertEqual(environment['PATH'].split(':')[0], str(Path(sys.executable).parent))
            self.assertEqual(Path(cwd).resolve(), ws.worktrees.resolve())
            self.assertTrue(Path(environment['TMPDIR']).is_dir())
            self.assertTrue(await host.cleanup(attempt))
            self.assertFalse(Path(environment['TMPDIR']).exists())

    async def test_unlisted_variables_are_not_passed_even_when_present(self):
        with workspace() as ws:
            host = runtime(ws)
            with patch.dict(os.environ, {'XDG_RUNTIME_DIR': '/run/user/fixture'}):
                attempt, process = await launch(host, ws, argv=[sys.executable, '-c', 'import os;print("XDG_RUNTIME_DIR" in os.environ)'])
            raw, _ = await process.communicate()
            self.assertEqual(raw.strip(), b'False')
            await host.cleanup(attempt)

    async def test_spawn_records_process_identity_before_returning(self):
        with workspace() as ws:
            host = runtime(ws)
            records = []
            host.record = lambda kind, value: records.append((kind, value))
            attempt, process = await launch(host, ws)
            process_identity = host.entries[attempt]['process']
            self.assertEqual(process_identity['pid'], process.pid)
            self.assertTrue(process_identity['start_ticks'])
            self.assertTrue(process_identity['boot_id'])
            self.assertEqual([kind for kind, _ in records], ['execution_intent', 'execution_identity'])
            persisted = json.loads((host.root / 'execution.json').read_text())
            self.assertEqual(persisted[attempt]['process']['pid'], process.pid)
            self.assertTrue(await host.cleanup(attempt))

    async def test_cleanup_stops_the_group_including_descendants_and_is_idempotent(self):
        with workspace() as ws:
            host = runtime(ws)
            script = 'import subprocess,time;subprocess.Popen(["/usr/bin/sleep","60"]);time.sleep(60)'
            attempt, process = await launch(host, ws, argv=[sys.executable, '-c', script])
            await asyncio.sleep(.3)
            self.assertTrue(alive(process.pid))
            self.assertTrue(await host.cleanup(attempt))
            self.assertFalse(alive(process.pid))
            self.assertFalse(host.entries)
            self.assertTrue(await host.cleanup(attempt))
            self.assertTrue(await host.reserve(str(uuid4()), 'worker', 'pi'))

    async def test_restart_recovery_stops_a_surviving_group_it_can_identify(self):
        with workspace() as ws:
            first = runtime(ws)
            attempt, process = await launch(first, ws)
            self.assertTrue(alive(process.pid))
            restarted = runtime(ws)  # Same ledger; no handle to the child.
            self.assertIn(attempt, restarted.entries)
            self.assertEqual(await restarted.recover(), {attempt: True})
            self.assertFalse(alive(process.pid))
            self.assertFalse(restarted.entries)

    async def test_reused_pid_is_never_killed(self):
        with workspace() as ws:
            host = runtime(ws)
            unrelated = subprocess.Popen(['/usr/bin/sleep', '60'], start_new_session=True)
            try:
                attempt = str(uuid4())
                self.assertTrue(await host.reserve(attempt, 'worker', 'pi'))
                host.entries[attempt]['process'] = dict(pid=unrelated.pid, start_ticks='1',
                                                        boot_id=host.boot_id)
                self.assertTrue(await host.cleanup(attempt))
                self.assertIsNone(unrelated.poll())  # Identity differs; left alone.
            finally:
                unrelated.kill()
                unrelated.wait()

    async def test_process_from_an_earlier_boot_is_treated_as_gone(self):
        with workspace() as ws:
            host = runtime(ws)
            unrelated = subprocess.Popen(['/usr/bin/sleep', '60'], start_new_session=True)
            try:
                attempt = str(uuid4())
                self.assertTrue(await host.reserve(attempt, 'worker', 'pi'))
                ticks = Path(f'/proc/{unrelated.pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
                host.entries[attempt]['process'] = dict(pid=unrelated.pid, start_ticks=ticks, boot_id='earlier-boot')
                self.assertTrue(await host.cleanup(attempt))
                self.assertIsNone(unrelated.poll())
            finally:
                unrelated.kill()
                unrelated.wait()

    async def test_unconfirmed_termination_retains_the_reservation_until_confirmed(self):
        with workspace() as ws:
            host = runtime(ws)
            host.grace, host.kill_wait = .05, .05
            attempt, process = await launch(host, ws)
            # Signals that do not land model a group that survives termination.
            with patch('cursus.host.os.killpg'):
                self.assertFalse(await host.cleanup(attempt))
            self.assertEqual(host.entries[attempt]['state'], 'uncertain')
            self.assertEqual(len(host.entries), 1)
            self.assertTrue(alive(process.pid))
            self.assertTrue(await host.cleanup(attempt))  # Real signals now confirm the stop.
            self.assertFalse(alive(process.pid))
            self.assertFalse(host.entries)

    async def test_workspace_must_be_an_absolute_non_symlink_directory(self):
        with workspace() as ws:
            host = runtime(ws)
            link = ws.root / 'link'
            link.symlink_to(ws.worktrees)
            for bad in (link, Path('relative')):
                attempt = str(uuid4())
                await host.reserve(attempt, 'worker', 'pi')
                with self.assertRaises(Problem):
                    await host.prepare(attempt, bad)

    async def test_settings_reject_unknown_and_unsafe_values(self):
        from cursus.config import execution_settings
        execution_settings(dict(disk_reserve_mb=1, host_reserve_mb=1))
        execution_settings(dict(disk_reserve_mb=1, host_reserve_mb=1, pass_env=['XDG_RUNTIME_DIR'], path='/usr/local/bin:/usr/bin'))
        for bad in (dict(disk_reserve_mb=1), dict(disk_reserve_mb=1, host_reserve_mb=1, extra=1),
                    dict(disk_reserve_mb=1, host_reserve_mb=1, pass_env=['lower']),
                    dict(disk_reserve_mb=1, host_reserve_mb=1, pass_env=['HOME']),
                    dict(disk_reserve_mb=1, host_reserve_mb=1, path='relative:/usr/bin'),
                    dict(disk_reserve_mb=0, host_reserve_mb=1)):
            with self.assertRaises(Problem):
                execution_settings(bad)


class RunnerRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_ledger_recovers_identity_from_launch_journal(self):
        from cursus.runner import Journal, Runner
        with workspace() as ws:
            host = runtime(ws)
            journal = Journal(ws.state / 'journal')
            Runner(str(uuid4()), journal, None, execution=SimpleNamespace(runtime=host))
            attempt, process = await launch(host, ws)
            host.path.unlink()  # Loss cannot turn a surviving execution into absence.
            restarted = runtime(ws)
            self.assertNotIn(attempt, restarted.entries)
            Runner(str(uuid4()), journal, None, execution=SimpleNamespace(runtime=restarted))
            self.assertIn(attempt, restarted.entries)
            self.assertEqual(restarted.entries[attempt]['process']['pid'], process.pid)
            self.assertEqual(await restarted.recover(), {attempt: True})
            self.assertFalse(alive(process.pid))
            journal.close()

    def test_compaction_bounds_history_and_preserves_unresolved_launch(self):
        from cursus.runner import Journal
        with workspace() as ws:
            journal = Journal(ws.state)
            journal.compaction = True
            unresolved = str(uuid4())
            journal.record('grant', dict(attempt_id=unresolved, request_id=str(uuid4())))
            journal.record('launch', unresolved)
            for _ in range(200):
                request, attempt = str(uuid4()), str(uuid4())
                journal.record('pending', dict(id=request, slot='worker'))
                journal.record('grant', dict(attempt_id=attempt, request_id=request))
                journal.record('launch', attempt)
                journal.record('execution_intent', dict(attempt=attempt))
                journal.record('retire', request)
            self.assertEqual(len(journal.records), 3)
            self.assertLess(journal.path.stat().st_size, 2048)
            generation = journal.generation
            journal.close()
            journal = Journal(ws.state)
            self.assertEqual(journal.generation, generation)
            self.assertIn(dict(kind='launch', value=unresolved), journal.records)
            journal.close()

    async def test_stop_recovery_waits_for_unknown_final_receipt(self):
        from cursus.runner import Journal, Runner
        with workspace() as ws:
            journal = Journal(ws.state / 'journal')
            attempt = str(uuid4())
            journal.record('grant', dict(attempt_id=attempt, request_id=str(uuid4())))
            journal.record('launch', attempt)
            journal.record('execution_removed', attempt)
            journal.record('event', dict(attempt_id=attempt, seq=2, kind='final', payload={'kind': 'unknown'}))
            journal.record('ack', dict(attempt_id=attempt, committed_through=1))
            observations = []

            class Wire:
                async def exchange(self, route, value, *args):
                    observations.append(value['observations'][0]['kind'])
                    return dict(dispositions={}, held_claims=[], commands=[], reconciled=True)
            runner = Runner(str(uuid4()), journal, Wire(), execution=SimpleNamespace(runtime=runtime(ws)))
            await runner.reconcile()
            self.assertEqual(observations[-1], 'terminal_pending')
            journal.record('ack', dict(attempt_id=attempt, committed_through=2))
            await runner.reconcile()
            self.assertEqual(observations[-1], 'stopped')
            journal.close()


class ExecutionConstructionTests(unittest.TestCase):
    def test_execution_requires_the_host_runtime_and_holds_only_installed_paths(self):
        from cursus.execution import Execution
        with self.assertRaises(Problem):
            Execution({'claude': '/bin/claude'}, None)
        host = object()
        execution = Execution({'claude': '/bin/claude'}, host)
        self.assertIs(execution.runtime, host)
        self.assertEqual(execution.clis, {'claude': '/bin/claude'})

    def test_authorize_uses_the_recipe_and_refuses_missing_or_non_executable_clis(self):
        from cursus.execution import Execution
        with workspace() as ws:
            binary = ws.root / 'claude'
            binary.write_text('#!/bin/sh\n')
            invocation = {'role': dict(name='planner', cli='claude', model='m', reasoning='r', tier='organization',
                                       tools=['read']), 'registry_commit': '0' * 40}
            with self.assertRaises(Problem) as missing:
                Execution({}, object()).authorize(invocation)
            self.assertEqual(missing.exception.code, 'cli_missing')
            execution = Execution({'claude': str(binary)}, object())
            with self.assertRaises(Problem):
                execution.authorize(invocation)  # Present but not executable.
            binary.chmod(0o755)
            argv, transport = execution.authorize(invocation)
            self.assertEqual((argv[0], transport), (str(binary), 'stdin'))
            self.assertIn('--safe-mode', argv)


if __name__ == '__main__':
    unittest.main()
