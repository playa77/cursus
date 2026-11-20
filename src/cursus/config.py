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
        result = subprocess.run(['git', '-c', 'safe.directory='+str(root), '-C', str(root), 'show', f'{commit}:{relative}'],
                                capture_output=True, check=False)
        if result.returncode or result.stdout != item.read_bytes():
            fail('Role/prompt files differ from the pinned release.')
    registry = tomllib.loads(path.read_text())
    keys(registry, ('schema_version', 'roles', 'profile_digest'))
    validate('Digest', registry['profile_digest'])
    if registry['schema_version'] != 1:
        fail()
    if not isinstance(registry['roles'],dict) or not {'interviewer','planner','worker','reviewer','scout','debug','advocate','critic','judge'} <= registry['roles'].keys():
        fail('Missing built-in role binding.')
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
        prompt = absolute(service['prompts_root']) / role['prompt']
        if prompt.suffix != '.md' or prompt.resolve().parent != absolute(service['prompts_root']).resolve():
            fail()
        role['prompt_text'] = prompt.read_text()
        role['name'] = name
    return registry


def load(process_kind, path):
    raw = absolute(path).read_bytes()
    try:
        settings = tomllib.loads(raw.decode())
    except (ValueError, UnicodeError):
        fail('Malformed TOML.')
    if process_kind == 'operator_cli':
        keys(settings, ('operator_socket',))
        absolute(settings['operator_socket'])
        return settings
    required = ('schema_version', 'process_kind', 'service', 'limits', 'capacity')
    if process_kind == 'control':
        keys(settings, (*required, 'runner', 'repositories', 'backup'))
        service = settings['service']
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
        settings['profile_digest'] = release['profile_digest']
        settings['dsn'] = secret(service['dsn_file'])
        settings['bearer_digest'] = validate('Digest', secret(settings['runner']['bearer_digest_file']))
        origin = service['external_origin']
    elif process_kind == 'runner':
        keys(settings, (*required, 'publisher', 'cli', 'execution_pool', 'resources', 'verification', 'pi_reviewer', 'repositories'))
        service = settings['service']
        keys(service, ('user', 'origin', 'runner_id', 'bearer_file', 'state_root', 'spool_root',
                       'repository_root', 'worktree_root', 'review_root', 'capabilities_file', 'capabilities_digest'))
        validate('Id', service['runner_id'])
        enrollment(settings['repositories'])
        keys(settings['publisher'], ('git_binary', 'git_credential_file', 'github_credential_file'))
        for configured in settings['publisher'].values():
            absolute(configured)
        keys(settings['cli'], ('pi', 'claude', 'codex', 'agy'))
        users = []
        for cli, identity in settings['cli'].items():
            keys(identity, ('binary','user','home','model'), ('provider','reasoning','auth_files'))
            auth = identity.get('auth_files',[])
            if not isinstance(auth,list) or any(not isinstance(name,str) for name in auth) or len(set(auth))!=len(auth):
                fail('Native auth files must be a unique list of relative file paths.')
            for name in auth:
                from cursus.contracts import _path
                _path(name)
            absolute(identity['binary'])
            absolute(identity['home'])
            users.append(identity['user'])
        keys(settings['verification'], ('user','home'))
        absolute(settings['verification']['home'])
        users.append(settings['verification']['user'])
        if len(set(users)) != len(users) or 'root' in users:
            fail('Execution identities must be distinct and unprivileged.')
        keys(settings['pi_reviewer'], ('enabled','user','home'), ('auth_files',))
        if settings['pi_reviewer']['enabled'] and (settings['pi_reviewer']['user'] in users or settings['pi_reviewer']['user'] == 'root'):
            fail('Pi review requires a distinct unprivileged identity.')
        absolute(settings['pi_reviewer']['home'])
        pool = settings['execution_pool']
        if not isinstance(pool,list) or len(pool)!=16:
            fail('Exactly 16 execution pool accounts are required.')
        for account in pool:
            keys(account, ('id','user','home'))
            absolute(account['home'])
            if account['user'] in users or account['user']=='root':
                fail('Pool identities must be separate from native credential identities.')
        for field in ('id','user','home'):
            if len({a[field] for a in pool})!=16:
                fail('Pool identities must be unique.')
        from cursus.resources import validate_resources
        validate_resources(settings['resources'])
        for key in ('state_root', 'spool_root', 'repository_root', 'worktree_root', 'review_root'):
            absolute(service[key])
        settings['bearer'] = secret(service['bearer_file'])
        profile = absolute(service['capabilities_file']).read_bytes()
        if sha256(profile).hexdigest() != service['capabilities_digest']:
            fail('Capability digest mismatch.')
        settings['profiles'] = tomllib.loads(profile.decode())
        settings['profiles']['digest'] = service['capabilities_digest']
        if settings['profiles'].get('qualification') != 'qualified':
            fail('Capability profile is not qualified.')
        for cli in ('pi','claude','codex','agy'):
            measured = settings['profiles'].get(cli, {})
            if measured.get('binary') != settings['cli'][cli]['binary'] or measured.get('user') != settings['cli'][cli]['user'] or measured.get('home') != settings['cli'][cli]['home']:
                fail('Measured binary/identity differs from runtime settings.')
        origin = service['origin']
    else:
        fail('Unsupported process kind.')
    from cursus.capacity import validate_capacity
    settings['capacity'] = validate_capacity(settings['capacity'])
    if process_kind=='control':
        settings['runner']['capacity'] = settings['capacity']
    if settings['schema_version'] != 1 or settings['process_kind'] != process_kind:
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
