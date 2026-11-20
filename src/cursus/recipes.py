"""Native CLI invocation recipes and the read-only preflight (ADR 0016).

The recipes are source, not operator-authored profiles: the roles file chooses a
CLI, model, reasoning and tool set; this module turns that into the exact argv.
Only the four direct CLI families are supported; there is no SDK or fallback.

Verification status: Claude Code's options were compared with an installed
2.1.330 `--help`. The codex, agy and pi recipes carry the 0.6.0 assumptions and
have not been compared with real installs; the preflight reports any option the
installed CLI does not advertise.
"""
import asyncio
import json
import os
from pathlib import Path
import re
import shutil
import signal
import tempfile
from cursus.contracts import Problem
from cursus.host import DEFAULT_PATH, child_environment

READ = ('read', 'list', 'search')
WRITE = READ + ('write', 'edit', 'bash')
# Model/reasoning/provider values become argv: no leading '-', spaces or shell characters.
VALUE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/@+-]*')
EXECUTABLES = {'pi': ('pi',), 'claude': ('claude',), 'codex': ('codex',), 'agy': ('agy', 'antigravity')}
MAX_OUTPUT = 1024 * 1024

CLAUDE_TOOLS = {'read': 'Read', 'list': 'Glob', 'search': 'Grep'}
PI_TOOLS = {'read': ['read'], 'list': ['ls'], 'search': ['find', 'grep'],
            'write': ['write'], 'edit': ['edit'], 'bash': ['bash']}
AGY_SETTINGS = {'permissions': {'deny': ['command(*)', 'write_file(*)', 'mcp(*)', 'web(*)']}}
PI_CLEAN = ['--no-extensions', '--no-skills', '--no-prompt-templates', '--no-themes']


def safe(value):
    return isinstance(value, str) and VALUE.fullmatch(value) is not None


def build(role, binary):
    """Return (argv, prompt_transport) for a role; raise Problem when it exceeds the recipe."""
    cli = role['cli']
    if cli not in EXECUTABLES:
        raise Problem('profile_mismatch', 'Unsupported CLI.')
    if role['tier'] not in ('production', 'organization') or (role['tier'] == 'production' and cli != 'pi'):
        raise Problem('profile_mismatch', 'Invalid production CLI.')
    tools = role['tools']
    allowed = WRITE if cli == 'pi' else READ
    if not isinstance(tools, list) or not tools or not all(isinstance(t, str) and t in allowed for t in tools):
        raise Problem('profile_mismatch', 'Role tools exceed what this CLI recipe supports.')
    if role['tier'] == 'organization' and set(tools) - set(READ):
        raise Problem('profile_mismatch', 'Reviewer/organization tools must be read-only.')
    model, reasoning, provider = role['model'], role['reasoning'], role.get('provider')
    if not safe(model) or not safe(reasoning) or (provider is not None and not safe(provider)):
        raise Problem('profile_mismatch', 'Model, reasoning or provider is not a plain identifier.')
    if not Path(binary).is_absolute():
        raise Problem('profile_mismatch', 'CLI binary must be an absolute path.')
    chosen = [t for t in allowed if t in tools]
    if cli == 'claude':
        argv = ['-p', '--output-format', 'stream-json', '--verbose', '--model', model, '--effort', reasoning,
                '--no-session-persistence', '--tools', ','.join(CLAUDE_TOOLS[t] for t in chosen), '--safe-mode']
        transport = 'stdin'
    elif cli == 'codex':
        argv = ['exec', '--json', '--model', model, '-c', f'model_reasoning_effort="{reasoning}"',
                '--sandbox', 'read-only', '--ignore-user-config', '--ephemeral']
        transport = 'stdin'
    elif cli == 'agy':
        argv = ['-p', '--output-format', 'stream-json', '--model', model, '--effort', reasoning, '--mode', 'plan',
                '--disable-slash-commands', '--settings', json.dumps(AGY_SETTINGS)]
        transport = 'stdin'
    else:
        writes = bool(set(tools) - set(READ))
        argv = ['--mode', 'rpc'] if writes else ['--mode', 'json', '--print']
        if provider:
            argv += ['--provider', provider]
        argv += ['--model', model, '--thinking', reasoning,
                 '--tools', ','.join(name for t in chosen for name in PI_TOOLS[t]), *PI_CLEAN]
        transport = 'rpc' if writes else 'argument'
    return [str(binary), *argv], transport


def required_options(cli):
    """Every long option any recipe argv for this CLI can contain."""
    base = dict(name='r', model='m', reasoning='r', provider='p', timeout_seconds=1)
    variants = [dict(tier='production', tools=list(WRITE)), dict(tier='production', tools=list(READ))] if cli == 'pi' \
        else [dict(tier='organization', tools=list(READ))]
    options = set()
    for variant in variants:
        argv, _ = build(dict(base, cli=cli, **variant), '/x')
        options.update(token for token in argv[1:] if token.startswith('--'))
    return sorted(options)


def resolve(cli, settings):
    """Absolute path of the operator's installed CLI, or None. Never installs or downloads."""
    def usable(path):
        return path.is_absolute() and path.is_file() and os.access(path, os.X_OK)
    configured = settings.get('clis', {}).get(cli)
    if configured:
        return str(configured) if usable(Path(configured)) else None
    for directory in settings.get('path', DEFAULT_PATH).split(':'):
        for name in EXECUTABLES[cli]:
            candidate = Path(directory) / name
            if usable(candidate):
                return str(candidate)
    return None


def discover(settings):
    found = {cli: resolve(cli, settings) for cli in EXECUTABLES}
    return {cli: path for cli, path in found.items() if path}


async def query(argv, environment, directory, timeout):
    process = await asyncio.create_subprocess_exec(*argv, cwd=directory, env=environment,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True)
    try:
        raw, error = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        raise Problem('preflight', 'query timed out') from None
    finally:
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()
    if len(raw) > MAX_OUTPUT or len(error) > MAX_OUTPUT:
        raise Problem('preflight', 'query output exceeds its bound')
    return process.returncode, raw.decode('utf-8', 'replace') + error.decode('utf-8', 'replace'), raw.decode('utf-8', 'replace')


async def preflight(cli, binary, settings, timeout=30):
    """Version and help queries only: no prompt, no inference, no login probe."""
    result = dict(cli=cli, binary=str(binary), version=None, missing=[], ok=False)
    with tempfile.TemporaryDirectory(prefix='cursus-preflight-') as directory:
        environment = child_environment(settings, binary, directory)
        try:
            code, _, text = await query([binary, '--version'], environment, directory, timeout)
            if code == 0:
                result['version'] = next((line.strip()[:200] for line in text.splitlines() if line.strip()), None)
            help_argv = [binary, 'exec', '--help'] if cli == 'codex' else [binary, '--help']
            code, text, _ = await query(help_argv, environment, directory, timeout)
        except (Problem, OSError) as exc:
            result['error'] = getattr(exc, 'message', None) or 'query failed: ' + type(exc).__name__
            return result
    if code:
        result['error'] = f'help query failed (exit {code})'
        return result
    result['missing'] = [o for o in required_options(cli) if not re.search(r'(?<![\w-])' + re.escape(o) + r'(?![\w-])', text)]
    result['ok'] = not result['missing']
    return result
