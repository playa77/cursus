"""In-source CLI recipes and the read-only preflight (ADR 0016).

Fixture executables only. Nothing here runs a model, a login or a provider call.
Only Claude Code's flags have been compared with a real installed CLI (manually);
the codex, agy and pi recipes carry over the 0.6.0 assumptions unverified.
"""
import json
import os
from pathlib import Path
import shlex
import unittest
from cursus.contracts import Problem
from cursus.recipes import READ, WRITE, build, discover, preflight, required_options, resolve, safe
from tests.support import workspace


def role(cli, tools=READ, **extra):
    value = dict(name='r', cli=cli, model='model-1', reasoning='medium',
                 tier='production' if cli == 'pi' else 'organization', tools=list(tools), timeout_seconds=5)
    value.update(extra)
    return value


def script(path, body):
    path.write_text('#!/bin/sh\n' + body)
    path.chmod(0o755)
    return str(path)


class BuildTests(unittest.TestCase):
    def test_claude_read_only(self):
        argv, transport = build(role('claude'), '/bin/claude')
        self.assertEqual(argv, ['/bin/claude', '-p', '--output-format', 'stream-json', '--verbose',
            '--model', 'model-1', '--effort', 'medium', '--no-session-persistence',
            '--tools', 'Read,Glob,Grep', '--safe-mode'])
        self.assertEqual(transport, 'stdin')

    def test_codex_read_only(self):
        argv, transport = build(role('codex'), '/bin/codex')
        self.assertEqual(argv, ['/bin/codex', 'exec', '--json', '--model', 'model-1', '-c',
            'model_reasoning_effort="medium"', '--sandbox', 'read-only', '--ignore-user-config', '--ephemeral'])
        self.assertEqual(transport, 'stdin')

    def test_agy_read_only(self):
        argv, transport = build(role('agy'), '/bin/agy')
        self.assertEqual(argv[:9], ['/bin/agy', '-p', '--output-format', 'stream-json', '--model', 'model-1',
                                    '--effort', 'medium', '--mode'])
        self.assertEqual(argv[9], 'plan')
        self.assertIn('--disable-slash-commands', argv)
        settings = json.loads(argv[argv.index('--settings') + 1])
        self.assertIn('command(*)', settings['permissions']['deny'])
        self.assertEqual(transport, 'stdin')

    def test_pi_with_write_tools_uses_rpc_and_exactly_the_role_tools(self):
        argv, transport = build(role('pi', WRITE, provider='prov'), '/bin/pi')
        self.assertEqual(argv[:9], ['/bin/pi', '--mode', 'rpc', '--provider', 'prov', '--model', 'model-1',
                                    '--thinking', 'medium'])
        self.assertEqual(argv[argv.index('--tools') + 1], 'read,ls,find,grep,write,edit,bash')
        self.assertEqual(transport, 'rpc')
        argv, _ = build(role('pi', ['read', 'write']), '/bin/pi')
        self.assertEqual(argv[argv.index('--tools') + 1], 'read,write')
        self.assertNotIn('--provider', argv)  # Optional; omitted when the role has none.
        for flag in ('--no-extensions', '--no-skills', '--no-prompt-templates', '--no-themes'):
            self.assertIn(flag, argv)

    def test_pi_read_only_uses_json_print_with_the_prompt_as_an_argument(self):
        argv, transport = build(role('pi', READ, provider='prov'), '/bin/pi')
        self.assertEqual(argv[1:4], ['--mode', 'json', '--print'])
        self.assertEqual(argv[argv.index('--tools') + 1], 'read,ls,find,grep')
        self.assertEqual(transport, 'argument')

    def test_authority_is_limited_by_cli_and_tier(self):
        for bad in (role('claude', ['read', 'write']), role('codex', WRITE), role('agy', ['bash']),
                    role('pi', ['read', 'teleport']), role('pi', []), role('claude', ['*']),
                    role('claude', READ, tier='production'), role('pi', ['write'], tier='organization'),
                    role('pi', READ, tier='other'), role('nonesuch')):
            with self.assertRaises(Problem, msg=str(bad)):
                build(bad, '/bin/x')

    def test_values_cannot_inject_options(self):
        for field in ('model', 'reasoning', 'provider'):
            for bad in ('--evil', '-x', 'two words', 'a;b', '', 'new\nline', '$(x)'):
                with self.assertRaises(Problem, msg=field + repr(bad)):
                    build(role('pi', WRITE, **{field: bad}), '/bin/pi')
        self.assertTrue(safe('deepseek-v4.1-flash') and safe('vendor/model:1@2+3'))

    def test_the_binary_must_be_absolute(self):
        with self.assertRaises(Problem):
            build(role('claude'), 'claude')


class ResolveTests(unittest.TestCase):
    def test_configured_path_then_search_path_with_antigravity_alias(self):
        with workspace() as ws:
            bin1, bin2 = ws.root / 'one', ws.root / 'two'
            bin1.mkdir(), bin2.mkdir()
            script(bin1 / 'claude', 'exit 0\n')
            script(bin2 / 'antigravity', 'exit 0\n')
            (bin2 / 'codex').write_text('not executable')
            settings = dict(path=f'{bin1}:{bin2}')
            self.assertEqual(resolve('claude', settings), str(bin1 / 'claude'))
            self.assertEqual(resolve('agy', settings), str(bin2 / 'antigravity'))
            self.assertIsNone(resolve('codex', settings))
            self.assertIsNone(resolve('pi', settings))
            explicit = script(ws.root / 'custom-pi', 'exit 0\n')
            self.assertEqual(resolve('pi', dict(settings, clis={'pi': explicit})), explicit)
            self.assertIsNone(resolve('pi', dict(settings, clis={'pi': str(ws.root / 'missing')})))
            found = discover(dict(settings, clis={'pi': explicit}))
            self.assertEqual(found, {'claude': str(bin1 / 'claude'), 'agy': str(bin2 / 'antigravity'), 'pi': explicit})


class PreflightTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, ws, cli, include=None, version='fixture 1.2.3'):
        include = required_options(cli) if include is None else include
        calls = ws.root / (cli + '-calls')
        help_text = ' '.join(include)
        log, prompt = shlex.quote(str(calls)), shlex.quote(str(calls) + '.prompt')
        return script(ws.root / cli, f'echo "$@" >> {log}\ncase "$*" in\n'
                      f'  *--version*) echo "{version}";;\n  *--help*) echo "usage: {help_text}" >&2;;\n  *) echo PROMPT >> {prompt};;\nesac\n'), calls

    async def test_reports_version_and_runs_only_version_and_help(self):
        with workspace() as ws:
            for cli in ('claude', 'codex', 'agy', 'pi'):
                binary, calls = self.fixture(ws, cli)
                result = await preflight(cli, binary, {})
                self.assertEqual((result['ok'], result['missing'], result['version']), (True, [], 'fixture 1.2.3'), cli)
                recorded = calls.read_text().split('\n')
                self.assertTrue(all(('--version' in line or '--help' in line) for line in recorded if line), recorded)
                self.assertFalse(Path(str(calls) + '.prompt').exists())
            self.assertIn('exec --help', (ws.root / 'codex-calls').read_text())

    async def test_missing_options_are_named_and_fail_the_check(self):
        with workspace() as ws:
            binary, _ = self.fixture(ws, 'claude', include=['--model'])
            result = await preflight('claude', binary, {})
            self.assertFalse(result['ok'])
            self.assertIn('--safe-mode', result['missing'])
            self.assertNotIn('--model', result['missing'])

    async def test_a_hanging_or_failing_cli_is_reported_not_raised(self):
        with workspace() as ws:
            hang = script(ws.root / 'claude', 'sleep 30\n')
            result = await preflight('claude', hang, {}, timeout=.3)
            self.assertFalse(result['ok'])
            self.assertIn('timed out', result['error'])
            broken = script(ws.root / 'codex', 'exit 3\n')
            self.assertFalse((await preflight('codex', broken, {}))['ok'])

    async def test_children_get_only_the_allowlisted_environment(self):
        with workspace() as ws:
            out = ws.root / 'env'
            binary = script(ws.root / 'claude', f'env > {shlex.quote(str(out))}\n')
            os.environ['CURSUS_PARENT_SECRET'] = 'must-not-reach-child'
            try:
                await preflight('claude', binary, {})
            finally:
                del os.environ['CURSUS_PARENT_SECRET']
            names = {line.split('=', 1)[0] for line in out.read_text().splitlines()}
            self.assertNotIn('CURSUS_PARENT_SECRET', names)
            self.assertTrue({'PATH', 'HOME'} <= names)

    def test_required_options_cover_every_flag_the_recipe_can_emit(self):
        self.assertTrue({'--output-format', '--safe-mode', '--tools', '--no-session-persistence'} <= set(required_options('claude')))
        self.assertTrue({'--json', '--sandbox', '--ephemeral'} <= set(required_options('codex')))
        self.assertTrue({'--mode', '--print', '--no-extensions'} <= set(required_options('pi')))
        self.assertTrue({'--settings', '--disable-slash-commands'} <= set(required_options('agy')))


class PreflightCommandTests(unittest.TestCase):
    def run_command(self, *argv):
        import contextlib
        import io
        from cursus.bootstrap import main
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(['preflight', *argv])
        return code, output.getvalue()

    def files(self, ws, clis, installed):
        roles = ws.root / 'roles.toml'
        roles.write_text('schema_version = 2\n' + ''.join(
            f'[roles.r{i}]\ntier = "{"production" if cli == "pi" else "organization"}"\ncli = "{cli}"\n'
            for i, cli in enumerate(clis)))
        bin_dir = ws.root / 'bin'
        bin_dir.mkdir()
        for cli in installed:
            name = 'antigravity' if cli == 'agy' else cli
            script(bin_dir / name, 'case "$*" in *--version*) echo "v-%s";; *--help*) echo "%s" >&2;; esac\n' % (name, ' '.join(required_options(cli))))
        config = ws.root / 'runner.toml'
        config.write_text(f'[execution]\ndisk_reserve_mb = 1\nhost_reserve_mb = 1\npath = "{bin_dir}"\n')
        return roles, config

    def test_only_the_clis_the_roles_use_are_required(self):
        with workspace() as ws:
            roles, config = self.files(ws, ['claude', 'pi'], ['claude', 'pi'])  # codex and agy not installed
            code, text = self.run_command('--roles', str(roles), '--config', str(config))
            self.assertEqual(code, 0, text)
            self.assertIn('ok   claude', text)
            self.assertIn('ok   pi', text)
            self.assertNotIn('codex', text)
            self.assertIn('sign-in is not checked', text)

    def test_missing_cli_fails_with_an_actionable_message_and_alias_is_found(self):
        with workspace() as ws:
            roles, config = self.files(ws, ['claude', 'agy', 'codex'], ['claude', 'agy'])
            code, text = self.run_command('--roles', str(roles), '--config', str(config))
            self.assertEqual(code, 1)
            self.assertIn('FAIL codex: not found. Install it and sign in as this user', text)
            self.assertIn('ok   agy', text)  # Found as `antigravity`.
            self.assertIn('failed for 1 CLI(s)', text)

    def test_a_cli_missing_a_recipe_option_fails(self):
        with workspace() as ws:
            roles, config = self.files(ws, ['claude'], [])
            script(ws.root / 'bin' / 'claude', 'echo "--model" >&2\n')
            code, text = self.run_command('--roles', str(roles), '--config', str(config))
            self.assertEqual(code, 1)
            self.assertIn('missing options:', text)
            self.assertIn('--safe-mode', text)


if __name__ == '__main__':
    unittest.main()
