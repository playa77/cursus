"""Startup-only configuration; no credentials enter immutable job snapshots."""

from hashlib import sha256
from pathlib import Path
import stat
import subprocess
import tomllib
from urllib.parse import urlsplit

from cursus.contracts import Problem, validate


def fail(message='Invalid configuration.'):
    raise Problem('invalid_config', message)


def keys(value, required, optional=()):
    if not isinstance(value, dict) or set(required) - value.keys() or value.keys() - set(required) - set(optional):
        fail('Missing or unsupported configuration key.')


def absolute(value):
    if not isinstance(value, str) or not Path(value).is_absolute():
        fail('Expected an absolute configured path.')
    return Path(value)


def secret(path):
    path = absolute(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        fail('Secret file must be private and regular.')
    return path.read_text().strip()


def enrollment(repositories):
    seen = set()
    for repo in repositories:
        keys(repo, ('owner', 'name', 'object_format', 'allowed_target_refs', 'checks', 'phase_check_ids'))
        if repo['object_format'] not in ('sha1', 'sha256'):
            fail()
        token = (repo['owner'], repo['name'])
        if token in seen or not repo['allowed_target_refs']:
            fail()
        seen.add(token)
        for ref in repo['allowed_target_refs']:
            validate('Repo', dict(owner=repo['owner'], name=repo['name'], target_ref=ref))
        checks = set()
        for check in repo['checks']:
            keys(check, ('id', 'argv', 'cwd', 'timeout_seconds'))
            if check['id'] in checks or not check['argv'] or not all(isinstance(x, str) and x for x in check['argv']):
                fail()
            absolute(check['argv'][0])
            if check['cwd'] != '.':
                from cursus.contracts import _path
                _path(check['cwd'])
            positive(check['timeout_seconds'])
            checks.add(check['id'])
        if not repo['phase_check_ids'] or set(repo['phase_check_ids']) - checks:
            fail('Code enrollment requires known phase checks.')


def positive(value):
    if type(value) is not int or value <= 0:
        fail('Expected a positive limit.')


def role_release(service):
    path = absolute(service['roles_file'])
    root = path.parent
    commit = validate('Sha', service['role_release_commit'])
    paths = [path, *sorted(absolute(service['prompts_root']).glob('*.md'))]
    # Only committed role/prompt files are inspected; no complete environment or
    # credential directories are read. A dirty unrelated file is immaterial.
    for item in paths:
        relative = str(item.relative_to(root))
        result = subprocess.run(['git', '-c', 'safe.directory=' + str(root), '-C', str(root), 'show', f'{commit}:{relative}'],
                                capture_output=True, check=False)
        if result.returncode or result.stdout != item.read_bytes():
            fail('Role/prompt files differ from the pinned release.')
    registry = tomllib.loads(path.read_text())
    keys(registry, ('schema_version', 'roles'))
    if registry['schema_version'] != 2:
        fail()
    if set(('interviewer','planner','worker','reviewer','scout','debug','advocate','critic','judge')) - registry['roles'].keys():
        fail('Required roles are missing.')
    for name, role in registry['roles'].items():
        keys(role, ('tier', 'cli', 'model', 'reasoning', 'tools', 'timeout_seconds', 'prompt'), ('provider',))
        if any('REPLACE_' in str(role.get(k, '')) for k in ('model','provider','reasoning')) or 'openrouter' in str(role.get('provider','')).lower():
            fail('Role invocation tuple is not qualified.')
        if role['cli'] not in ('pi', 'claude', 'codex', 'agy') or any('*' in tool for tool in role['tools']):
            fail('Invalid CLI or wildcard authority.')
        if role['tier'] not in ('production', 'organization'):
            fail()
        if role['tier'] == 'production' and role['cli'] != 'pi':
            fail('Production requires pi.')
        if role['tier'] == 'organization' and set(role['tools']) - {'read', 'list', 'search'}:
            fail('Organizational roles require read-only tools.')
        positive(role['timeout_seconds'])
        from cursus.recipes import safe
        if not all(safe(role[k]) for k in ('model','reasoning')) or ('provider' in role and not safe(role['provider'])):
            fail('Role model, reasoning and provider must be plain identifiers.')
        prompt = absolute(service['prompts_root']) / role['prompt']
        if prompt.suffix != '.md' or prompt.resolve().parent != absolute(service['prompts_root']).resolve():
            fail()
        role['prompt_text'] = prompt.read_text()
        role['name'] = name
    return registry


def load(process_kind, path, release_root=None):
    raw = absolute(path).read_bytes()
    try:
        settings = tomllib.loads(raw.decode())
    except (ValueError, UnicodeError):
        fail('Malformed TOML.')
    if process_kind == 'operator_cli':
        keys(settings, ('operator_socket',))
        absolute(settings['operator_socket'])
        return settings
    required = ('schema_version', 'process_kind', 'service', 'limits')
    if process_kind == 'control':
        keys(settings, (*required, 'runner', 'repositories', 'backup', 'capacity'))
        if 'capacity' in settings:
            capacity(settings['capacity'])
        service = settings['service']
        if release_root is not None:
            staged = absolute(release_root)
            for key in ('roles_file','prompts_root'):
                configured = absolute(service[key])
                if configured.is_relative_to('/opt/cursus/current'):
                    service[key] = str(staged / configured.relative_to('/opt/cursus/current'))
        keys(service, ('user', 'group', 'operator_group', 'listen_host', 'listen_port',
                       'operator_socket', 'external_origin', 'operator_login', 'dsn_file',
                       'artifact_root', 'roles_file', 'prompts_root', 'role_release_commit'))
        if service['listen_host'] != '127.0.0.1':
            fail('Control must bind loopback.')
        keys(settings['runner'], ('id', 'tailnet_node', 'bearer_digest_file'))
        validate('Id', settings['runner']['id'])
        keys(settings['backup'], ('root', 'off_host_destination'))
        absolute(settings['backup']['root'])
        enrollment(settings['repositories'])
        release = role_release(service)
        settings['roles'] = release['roles']
        settings['dsn'] = secret(service['dsn_file'])
        settings['bearer_digest'] = validate('Digest', secret(settings['runner']['bearer_digest_file']))
        origin = service['external_origin']
    elif process_kind == 'runner':
        keys(settings, (*required, 'publisher', 'capacity', 'execution', 'repositories'))
        service = settings['service']
        keys(service, ('user', 'origin', 'runner_id', 'bearer_file', 'state_root', 'spool_root',
                       'repository_root', 'worktree_root', 'review_root'))
        validate('Id', service['runner_id'])
        for key in ('state_root', 'spool_root', 'repository_root', 'worktree_root', 'review_root'):
            absolute(service[key])
        enrollment(settings['repositories'])
        keys(settings['publisher'], ('git_binary', 'git_credential_file', 'github_credential_file'))
        for configured in settings['publisher'].values():
            absolute(configured)
        capacity(settings['capacity'])
        execution_settings(settings['execution'])
        settings['bearer'] = secret(service['bearer_file'])
        origin = service['origin']
    else:
        fail('Unsupported process kind.')
    if settings['schema_version'] != (2 if process_kind == 'runner' or 'capacity' in settings else 1) or settings['process_kind'] != process_kind:
        fail()
    parsed = urlsplit(origin)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        fail('Expected an exact HTTPS origin.')
    allowed_limits = {'long_poll_seconds','heartbeat_seconds','unreachable_after_missed_heartbeats',
        'repair_retries','interrupted_retries','debate_rounds','debug_turns','interview_rounds',
        'request_bytes','spec_bytes','log_event_bytes','events_per_batch','artifact_bytes',
        'phase_artifact_bytes','runner_spool_bytes'} if process_kind == 'control' else {'long_poll_seconds','heartbeat_seconds','spool_bytes'}
    keys(settings['limits'], allowed_limits)
    for name, value in settings['limits'].items():
        positive(value)
        if name == 'debate_rounds' and value > 3:
            fail()
    return settings


def capacity(value):
    keys(value, ('worker','claude','codex','agy','verifier','repository'))
    for key, number in value.items():
        positive(number)
        if key == 'worker' and number > 4 or key in ('claude','codex','agy') and number > 2:
            fail('Configured agent ceiling is outside the accepted range.')
        if key in ('repository', 'verifier') and number != 1:
            fail('Repository and verifier remain independent single lanes.')


def execution_settings(value):
    """Host-native execution policy (ADR 0016). No isolation settings exist."""
    import re
    keys(value, ('disk_reserve_mb', 'host_reserve_mb'), ('path', 'pass_env', 'clis'))
    positive(value['disk_reserve_mb'])
    positive(value['host_reserve_mb'])
    if 'path' in value:
        directories = value['path'].split(':') if isinstance(value['path'], str) else []
        if not directories or not all(d.startswith('/') and '\n' not in d for d in directories):
            fail('Execution PATH must be absolute directories separated by colons.')
    clis = value.get('clis', {})
    if not isinstance(clis, dict) or set(clis) - {'pi', 'claude', 'codex', 'agy'} or not all(
            isinstance(c, str) and c.startswith('/') for c in clis.values()):
        fail('execution.clis must map pi/claude/codex/agy to absolute binary paths.')
    names = value.get('pass_env', [])
    base = {'PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'TMPDIR'}
    if not isinstance(names, list) or any(
            not isinstance(n, str) or not re.fullmatch('[A-Z_][A-Z0-9_]*', n) or n in base for n in names):
        fail('pass_env must list uppercase variable names other than the always-set ones.')
