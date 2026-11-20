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
    keys(registry, ('schema_version', 'roles', 'profile_digest'))
    validate('Digest', registry['profile_digest'])
    if registry['schema_version'] != 1:
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
        settings['profile_digest'] = release['profile_digest']
        settings['dsn'] = secret(service['dsn_file'])
        settings['bearer_digest'] = validate('Digest', secret(settings['runner']['bearer_digest_file']))
        origin = service['external_origin']
    elif process_kind == 'runner':
        keys(settings, (*required, 'publisher', 'capacity', 'containers', 'repositories'))
        service = settings['service']
        keys(service, ('user', 'origin', 'runner_id', 'bearer_file', 'state_root', 'spool_root',
                       'repository_root', 'worktree_root', 'review_root', 'capabilities_file', 'capabilities_digest'))
        validate('Id', service['runner_id'])
        for key in ('state_root', 'spool_root', 'repository_root', 'worktree_root', 'review_root'):
            absolute(service[key])
        enrollment(settings['repositories'])
        keys(settings['publisher'], ('git_binary', 'git_credential_file', 'github_credential_file'))
        for configured in settings['publisher'].values():
            absolute(configured)
        capacity(settings['capacity'])
        container_settings(settings['containers'], settings['capacity'], service, settings['publisher'])
        settings['bearer'] = secret(service['bearer_file'])
        profile = absolute(service['capabilities_file']).read_bytes()
        if sha256(profile).hexdigest() != service['capabilities_digest']:
            fail('Capability digest mismatch.')
        settings['profiles'] = tomllib.loads(profile.decode())
        settings['profiles']['digest'] = service['capabilities_digest']
        if settings['profiles'].get('qualification') not in ('qualified','native-checked'):
            fail('Capability profile has not completed native setup checks.')
        if settings['profiles'].get('image') != settings['containers']['image']:
            fail('Capability profile image differs from execution image.')
        for cli in ('pi','claude','codex','agy'):
            measured = settings['profiles'].get(cli, {})
            capability(cli, measured)
            if Path(measured.get('binary', '')).name != cli:
                fail('Required direct native binary is missing.')
            if measured.get('credential_concurrency', 0) < settings['capacity']['worker' if cli == 'pi' else cli]:
                fail('Native credential concurrency is not qualified at the requested ceiling.')
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


def container_settings(value, ceilings, service, publisher):
    keys(value, ('binary','version','image','network','disk_reserve_mb','resources','budget','credentials'), ('native_keyring','hide_project_customizations'))
    for flag in ('native_keyring','hide_project_customizations'):
        if flag in value and type(value[flag]) is not bool:
            fail('Native container feature switches must be booleans.')
    if value['binary'] != '/usr/bin/podman' or not value['version'].startswith('5.'):
        fail('This release supports an explicitly pinned Podman 5.x version.')
    import re
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', value['image']):
        fail('Execution image must be a locally qualified immutable image ID.')
    if value['network'] != 'private':
        fail('Agents require a private network namespace; host networking is forbidden.')
    positive(value['disk_reserve_mb'])
    keys(value['budget'], ('memory_mb','cpu_millis','pids','host_reserve_mb','host_reserve_cpu_millis'))
    for n in value['budget'].values():
        positive(n)
    if value['budget']['memory_mb'] + value['budget']['host_reserve_mb'] > 12 * 1024 or value['budget']['cpu_millis'] + value['budget']['host_reserve_cpu_millis'] > 6000:
        fail('Execution budget exceeds fixed VPS-A hardware after the host reserve.')
    keys(value['resources'], ('agent','verifier'))
    for resource in value['resources'].values():
        keys(resource, ('memory_mb','cpu_millis','pids','tmp_mb','home_mb'))
        for n in resource.values():
            positive(n)
        if resource['tmp_mb'] + resource['home_mb'] >= resource['memory_mb']:
            fail('Tmpfs limits must leave execution memory within the cgroup limit.')
    for key in ('memory_mb','cpu_millis','pids'):
        if sum(r[key] for r in value['resources'].values()) > value['budget'][key]:
            fail('Budget must admit an agent and a verifier simultaneously.')
    keys(value['credentials'], ('pi','claude','codex','agy'))
    ids, sources = set(), []
    forbidden = [absolute(service[k]).resolve() for k in ('state_root','spool_root','repository_root','worktree_root','review_root','bearer_file','capabilities_file')]
    forbidden += [absolute(p).resolve() for p in publisher.values()]
    for cli, domains in value['credentials'].items():
        if len(domains) != ceilings['worker' if cli == 'pi' else cli]:
            fail('Provide one independent native credential domain per requested concurrent session.')
        for domain in domains:
            keys(domain, ('id','evidence','mounts'))
            if domain['id'] in ids or not domain['evidence'] or 'REPLACE_' in domain['evidence'] or not domain['mounts']:
                fail('Credential domains need unique IDs, explicit mounts and qualification records.')
            ids.add(domain['id'])
            targets = []
            for mount in domain['mounts']:
                keys(mount, ('source','target'))
                source, target = absolute(mount['source']).resolve(), absolute(mount['target'])
                if any(str(p) in str(mount['source']) for p in (':', ',', '\n')):
                    fail('Unsupported mount source delimiter.')
                if target == Path('/home/session') or not target.is_relative_to('/home/session') or '..' in target.parts:
                    fail('Only explicit native auth subdirectories under disposable HOME may persist.')
                if any(source == other or source.is_relative_to(other) or other.is_relative_to(source) for other in sources + forbidden):
                    fail('Credential mounts overlap another domain or management path.')
                if any(target == other or target.is_relative_to(other) or other.is_relative_to(target) for other in targets):
                    fail('Credential target mounts overlap.')
                targets.append(target)
                sources.append(source)


def capability(cli, profile):
    required = ('binary','binary_digest','version','model','reasoning','qualified_roles',
                'fixed_argv','prompt_transport','tool_allowlist','clean_config_argv','probe_evidence',
                'credential_concurrency')
    optional = {'provider','role_profiles','read_only_argv','success_signature','failure_signature','turn_terminal_signature','control_correlation','renewal_procedure'}
    if not isinstance(profile,dict) or set(required)-profile.keys() or profile.keys()-set(required)-optional:
        fail('Capability profile is incomplete.')
    absolute(profile['binary'])
    validate('Digest',profile['binary_digest'])
    for field in ('version','model','reasoning'):
        if not isinstance(profile[field],str) or not profile[field] or 'REPLACE_' in profile[field]:
            fail('Capability tuple is not qualified.')
    for field in ('qualified_roles','fixed_argv','tool_allowlist','clean_config_argv','probe_evidence'):
        if not isinstance(profile[field],list) or not profile[field] or not all(isinstance(s,str) and s for s in profile[field]):
            fail('Capability argv/roles/probe evidence is incomplete.')
    if '*' in profile['tool_allowlist'] or 'openrouter' in str(profile.get('provider','')).lower():
        fail('Capability grants forbidden authority/provider.')
    if profile['prompt_transport'] not in ('stdin','argument','rpc') or profile['prompt_transport']=='rpc' and cli!='pi':
        fail('Unsupported native prompt transport.')
    required_tokens = {'pi':['--mode','rpc' if profile['prompt_transport']=='rpc' else 'json'],
                       'claude':['-p','--output-format','stream-json'],
                       'codex':['exec','--json'], 'agy':['-p','--output-format','stream-json']}[cli]
    if any(token not in profile['fixed_argv'] for token in required_tokens):
        fail('Capability must invoke the required native CLI family directly.')
    for override in profile.get('role_profiles',{}).values():
        capability(cli,{**profile,**override,'role_profiles':{}})
