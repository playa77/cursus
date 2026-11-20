#!/usr/bin/env python3
"""Ubuntu 26.04 installer, 2026-11-20-r4. Dry-run by default; no native login."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import tomllib


sys.path.insert(0, str(Path(__file__).resolve().parent.parent/'src'))
from cursus.contracts import Problem


def log(message):
    print(datetime.now(timezone.utc).isoformat() + ' ' + message, flush=True)


class Installer:
    def __init__(self, args):
        self.args = args
        self.source = Path(__file__).resolve().parent.parent
        self.user = 'cursus-runner' if args.host == 'worker' else 'cursus-control'
        self.service = 'cursus-runner' if args.host == 'worker' else 'cursus-control'
        from hashlib import sha256
        config_id = sha256(Path(args.config).read_bytes()).hexdigest()[:16] if args.config else 'unconfigured'
        self.release = Path('/opt/cursus/releases') / (args.release + '-' + config_id)
        self.reuse = False
        self.current = Path('/opt/cursus/current')
        self.config = None

    def run(self, argv, capture=False):
        log(('PLAN ' if not self.args.apply else 'RUN ') + ' '.join(map(str, argv)))
        if self.args.apply:
            return subprocess.run(list(map(str, argv)), check=True, capture_output=capture, text=True)

    def preflight(self):
        if not re.fullmatch('[0-9a-f]{40}', self.args.release):
            raise RuntimeError('Use the full reviewed source commit as --release.')
        if self.args.activate and not self.args.config:
            raise RuntimeError('Activation requires an explicit complete --config.')
        if self.args.config:
            original = Path(self.args.config)
            path = original.resolve(strict=True)
            if original.is_symlink() or not path.is_file():
                raise RuntimeError('Config must be a regular explicit file.')
            self.config = tomllib.loads(path.read_text())
            if self.config['schema_version'] != 2:
                raise RuntimeError('Schema 1/account-pool configuration requires deliberate migration.')
            # Structural validation does not open native credential material.
            sys.path.insert(0, str(self.source/'src'))
            from cursus.config import capacity, container_settings
            capacity(self.config['capacity'])
            if self.args.host == 'worker':
                container_settings(self.config['containers'], self.config['capacity'], self.config['service'], self.config['publisher'])
                if self.config['service']['user'] != self.user:
                    raise RuntimeError('Runner must use the stable rootless service account.')
            else:
                if self.config['service']['listen_host'] != '127.0.0.1':
                    raise RuntimeError('Controller listener must stay loopback-only.')
            if 'REPLACE_' in path.read_text():
                raise RuntimeError('Supplied config still contains replacement markers.')
        if not self.args.apply:
            log('Dry-run: no packages, accounts, database, files or services will be changed.')
            return
        if os.geteuid() != 0:
            raise RuntimeError('--apply requires root on the intended host.')
        if Path('/etc/os-release').read_text().find('VERSION_ID="26.04"') < 0 or 'ID=ubuntu' not in Path('/etc/os-release').read_text():
            raise RuntimeError('This installer supports Ubuntu Server 26.04 only.')
        if not self.args.activate_existing and not self.args.wheelhouse:
            raise RuntimeError('--apply requires a prepared hash-locked offline --wheelhouse.')
        if not self.args.activate_existing and subprocess.check_output(['git','-c','safe.directory='+str(self.source),'-C',str(self.source),'rev-parse','HEAD'], text=True).strip() != self.args.release:
            raise RuntimeError('Source HEAD differs from --release.')
        if not self.args.activate_existing and subprocess.check_output(['git','-c','safe.directory='+str(self.source),'-C',str(self.source),'status','--porcelain'], text=True).strip():
            raise RuntimeError('Source must be clean before staging an immutable release.')
        if self.args.activate_existing and self.args.config and Path(self.args.config).read_bytes() != (self.release/'config.toml').read_bytes():
            raise RuntimeError('Supplied config differs from immutable staged config; stage a new release.')
        if self.release.exists() and not self.args.activate_existing:
            marker = self.release/'complete.json'
            if not marker.is_file() or json.loads(marker.read_text()).get('commit') != self.args.release:
                raise RuntimeError('Incomplete stage retained at '+str(self.release)+'; inspect this named stage before retry. No active release was replaced.')
            self.reuse = True

    def account(self):
        try:
            user = pwd.getpwnam(self.user)
        except KeyError:
            # A single service account; normal useradd allocates subordinate IDs
            # from host policy. No per-role/session host accounts are created.
            self.run(['useradd','--user-group','--create-home','--home-dir','/var/lib/'+self.user,
                      '--shell','/usr/sbin/nologin', self.user])
            return
        if user.pw_uid == 0 or user.pw_dir != '/var/lib/'+self.user or user.pw_shell != '/usr/sbin/nologin':
            raise RuntimeError('Conflicting stable service account; refusing reuse.')

    def prepare_host(self):
        packages = ['python3-venv','git','ca-certificates']
        packages += ['podman','uidmap','passt'] if self.args.host == 'worker' else ['postgresql']
        self.run(['apt-get','install','--yes','--no-install-recommends',*packages])
        self.account()
        self.run(['install','-d','-m','0700','-o',self.user,'-g',self.user,'/var/lib/'+self.user])
        if self.args.host == 'worker':
            self.run(['loginctl','enable-linger', self.user])
        if self.args.host == 'controller':
            self.run(['systemctl','start','postgresql'])
            self.run(['groupadd','--force','cursus-operators'])
            self.run(['usermod','--append','--groups','cursus-operators',self.user])
            # Peer-authenticated local service role: no password in argv/logs.
            sql = "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='cursus-control') THEN CREATE ROLE \"cursus-control\" LOGIN; END IF; END $$;"
            if self.args.apply:
                subprocess.run(['runuser','-u','postgres','--','psql','--no-psqlrc','--set','ON_ERROR_STOP=1','--command',sql], check=True, stdout=subprocess.DEVNULL)
                result = subprocess.run(['runuser','-u','postgres','--','psql','--no-psqlrc','--tuples-only','--no-align','--command',"SELECT 1 FROM pg_database WHERE datname='cursus'"],check=True,capture_output=True,text=True)
                if result.stdout.strip() != '1':
                    self.run(['runuser','-u','postgres','--','createdb','--owner=cursus-control','cursus'])
            else:
                log('PLAN local PostgreSQL peer role cursus-control and owned database cursus; existing DB preserved.')

        roots = (['/etc/cursus/runner', '/var/lib/cursus-runner/state',
                  '/var/lib/cursus-runner/spool', '/var/lib/cursus-runner/repositories',
                  '/var/lib/cursus-runner/worktrees', '/var/lib/cursus-runner/reviews',
                  '/var/lib/cursus-runner/auth'] if self.args.host == 'worker' else
                 ['/etc/cursus/control', '/var/lib/cursus-control/artifacts', '/var/backups/cursus'])
        for name in roots:
            path = Path(name)
            if self.args.apply and (path.exists() or path.is_symlink()):
                account = pwd.getpwnam(self.user)
                if path.is_symlink() or not path.is_dir() or path.stat().st_uid != account.pw_uid:
                    raise RuntimeError('Refusing conflicting existing storage: '+name)
            self.run(['install','-d','-m','0700','-o',self.user,'-g',self.user,name])
        if self.args.host == 'worker':
            uid = pwd.getpwnam(self.user).pw_uid if self.args.apply else 'SERVICE_UID'
            self.run(['systemctl','start','user@'+str(uid)+'.service'])

    def stage(self, prepared=False):
        if self.reuse:
            log('Reused complete immutable release and identical supplied config: '+str(self.release))
            return
        if not prepared:
            self.prepare_host()
        self.run(['install','-d','-m','0755',str(self.release)])
        self.run(['git','-c','safe.directory='+str(self.source),'-c','safe.directory='+str(self.source/'.git'),'clone','--local','--no-hardlinks','--no-checkout',str(self.source),str(self.release/'source')])
        self.run(['git','-C',str(self.release/'source'),'-c','core.hooksPath=/dev/null','checkout','--detach',self.args.release])
        self.run(['git','-C',str(self.release/'source'),'remote','remove','origin'])
        self.run(['python3','-m','venv',str(self.release/'venv')])
        python = self.release/'venv/bin/python'
        self.run([python,'-m','pip','install','--no-index','--find-links',self.args.wheelhouse or '/REQUIRED_WHEELHOUSE',
                  '--require-hashes','-r',self.release/'source/requirements.lock'])
        self.run([python,'-m','build','--wheel','--no-isolation','--outdir',self.release/'wheels',self.release/'source'])
        if self.args.apply:
            wheel, = (self.release/'wheels').glob('*.whl')
        else:
            wheel = self.release/'wheels/cursus-RELEASE-py3-none-any.whl'
        self.run([python,'-m','pip','install','--no-index','--no-deps',wheel])
        self.run([python,'-m','pip','check'])
        if self.args.config:
            self.run(['install','-m','0600','-o',self.user,'-g',self.user,self.args.config,self.release/'config.toml'])
        else:
            log('STAGED only: supply a complete explicit configuration before activation.')

        if self.args.apply:
            marker = self.release/'complete.json'
            with marker.open('x') as output:
                json.dump({'commit':self.args.release},output)
                output.flush()
                os.fsync(output.fileno())

    def manager(self, *args):
        if self.args.host == 'worker':
            uid = pwd.getpwnam(self.user).pw_uid if self.args.apply else 'SERVICE_UID'
            return self.run(['runuser','-u',self.user,'--','env','XDG_RUNTIME_DIR=/run/user/'+str(uid),
                'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/'+str(uid)+'/bus','systemctl','--user',*args])
        return self.run(['systemctl',*args])

    def ready_to_switch(self):
        if self.current.exists() and not self.current.is_symlink():
            raise RuntimeError('Current release must be an installer-owned symlink; refusing an unknown layout.')
        if not self.current.exists():
            if self.args.apply and self.args.host == 'worker' and subprocess.run(['systemctl','is-active','--quiet','cursus-runner'],check=False).returncode == 0:
                raise RuntimeError('Legacy system runner is active. Drain and stop it before rootless migration; no second backend will start.')
            return
        current_sql = self.current/'source/src/cursus/migrations'
        next_sql = self.release/'source/src/cursus/migrations'
        if self.args.apply:
            for migration in current_sql.glob('*.sql'):
                next_file = next_sql/migration.name
                if not next_file.exists() or migration.read_bytes() != next_file.read_bytes():
                    raise RuntimeError('Rollback/migration history is incompatible; keep drain and use a matching database restore boundary.')
        if self.args.host == 'controller':
            old = self.current/'venv/bin/cursus'
            with __import__('tempfile').NamedTemporaryFile(mode='w', suffix='.json') as intent:
                json.dump({'kind':'set_drain','enabled':True}, intent); intent.flush()
                os.chmod(intent.name,0o644)  # Non-secret local drain action.
                self.run(['runuser','-u',self.user,'--',old,'action','--input',intent.name], capture=True)
            result = self.run(['runuser','-u',self.user,'--',old,'status','--deployment'], capture=True)
            if self.args.apply:
                status = json.loads(result.stdout)
                if not status['drain'] or status['unresolved_attempts'] or status['queued_jobs']:
                    raise RuntimeError('Drain requested; existing attempts and queued phases must finish/reconcile before activation. Old release remains active.')
        else:
            if self.args.apply:
                sys.path.insert(0,str(self.current/'source/src'))
                from cursus.config import load
                from cursus.runner import HTTPS
                import asyncio
                config = load('runner', str(self.current/'config.toml'))
                state = Path(config['service']['state_root'])
                generation = next(json.loads(line)['record']['value'] for line in (state/'journal.jsonl').open() if json.loads(line)['record']['kind']=='generation')
                async def check():
                    client = HTTPS(config['service']['origin'],config['bearer'],generation)
                    return await client.exchange('runners/'+config['service']['runner_id']+'/deployment',{},str(__import__('uuid').uuid4()))
                status = asyncio.run(check())
                if not status['drain'] or status['unresolved_attempts'] or status['queued_jobs']:
                    raise RuntimeError('Controller must be drained with zero unresolved attempts and queued jobs before worker activation.')
                ledger = state/'execution/containers.json'
                if ledger.exists() and json.loads(ledger.read_text()):
                    raise RuntimeError('Worker container cleanup is pending; old release remains active.')
            else:
                log('PLAN require authenticated controller drain, zero unresolved attempts, empty local execution ledger.')

    def activate(self):
        self.ready_to_switch()
        kind = 'runner' if self.args.host == 'worker' else 'control'
        python = self.release/'venv/bin/python'
        # Program consumes approved secret files opaquely; stdout contains no settings.
        self.run(['runuser','-u',self.user,'--',python,'-c',
            'from cursus.config import load; import sys; load(sys.argv[1], sys.argv[2], release_root=sys.argv[3])',kind,self.release/'config.toml',self.release])
        if self.args.host == 'worker':
            self.run(['runuser','-u',self.user,'--','podman','--version'])
            self.run(['runuser','-u',self.user,'--','test','-f','/sys/fs/cgroup/cgroup.controllers'])
            if self.args.apply:
                for file in ('/etc/subuid','/etc/subgid'):
                    if not any(line.startswith(self.user+':') and int(line.strip().split(':')[2]) >= 65536 for line in Path(file).read_text().splitlines()):
                        raise RuntimeError('Rootless service account needs a non-overlapping subordinate UID/GID range of at least 65536; follow host allocation policy.')
        if self.args.host == 'worker':
            self.run(['runuser','-u',self.user,'--',python,'-c',
                'import asyncio,sys; from cursus.config import load; from cursus.containers import Containers; s=load("runner",sys.argv[1]); asyncio.run(Containers(s["containers"], s["service"]["state_root"]+"/execution",s["capacity"]).preflight())',self.release/'config.toml'])
        self.manager('stop', self.service)
        unit_root = '/var/lib/cursus-runner/.config/systemd/user' if self.args.host == 'worker' else '/etc/systemd/system'
        self.run(['install','-d','-m','0755','-o',self.user,'-g',self.user,unit_root])
        self.run(['install','-m','0644',self.release/('source/deploy/cursus-'+kind+'.service'),unit_root+'/'+self.service+'.service'])
        if self.args.host == 'worker' and self.config:
            budget = self.config['containers']['budget']
            text = '[Unit]\nDescription=Cursus execution budget\n[Slice]\nMemoryMax='+str(budget['memory_mb'])+'M\nCPUQuota='+str(budget['cpu_millis']/10)+'%\nTasksMax='+str(budget['pids'])+'\n'
            dropin = Path(unit_root)
            self.run(['install','-d','-m','0755',dropin])
            if self.args.apply:
                (dropin/'cursus-execution.slice').write_text(text)
                verifier = self.config['containers']['resources']['verifier']
                for lane in ('agents','verifier'):
                    values = {key: (budget[key]-verifier[key] if lane=='agents' else verifier[key]) for key in ('memory_mb','cpu_millis','pids')}
                    (dropin/('cursus-execution-'+lane+'.slice')).write_text('[Slice]\nMemoryMax='+str(values['memory_mb'])+'M\nCPUQuota='+str(values['cpu_millis']/10)+'%\nTasksMax='+str(values['pids'])+'\n')
            else:
                log('PLAN aggregate cgroup limits generated from the exact runtime budget.')
        if self.args.apply:
            previous = str(self.current.resolve()) if self.current.exists() else None
            link = self.current.with_name('current.next')
            link.symlink_to(self.release)
            os.replace(link,self.current)
            log('Activated immutable release; previous release: '+str(previous))
        else:
            log('PLAN atomic /opt/cursus/current switch; preserve previous release/config for rollback.')
        self.manager('daemon-reload')
        if self.args.host == 'worker':
            self.manager('start', 'cursus-execution.slice', 'cursus-execution-agents.slice', 'cursus-execution-verifier.slice')
        self.manager('enable','--now',self.service)
        self.manager('is-active','--quiet',self.service)
        log('Activation requested. Verify '+('service-account journalctl --user -u ' if self.args.host == 'worker' else 'journalctl -u ')+self.service+' and authenticated readiness; systemd active alone is not qualification. Controller remains drained on upgrade.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host', choices=('worker','controller'))
    parser.add_argument('--release', required=True, help='Full reviewed source commit')
    parser.add_argument('--config', help='Explicit complete TOML; never silently preserve conflicting config')
    parser.add_argument('--wheelhouse', help='Prepared offline directory matching requirements.lock')
    parser.add_argument('--apply', action='store_true', help='Apply to intended Ubuntu host; otherwise dry-run')
    parser.add_argument('--dry-run', action='store_true', help='Explicit no-change plan')
    parser.add_argument('--activate', action='store_true')
    parser.add_argument('--activate-existing', action='store_true', help='Activate an already staged immutable release')
    args = parser.parse_args()
    if args.dry_run and args.apply:
        parser.error('--dry-run and --apply conflict')
    try:
        installer = Installer(args)
        if args.activate_existing:
            if not args.config:
                raise RuntimeError('--activate-existing requires the exact staged --config.')
            args.activate = True
            # Existing stage is immutable; no install/copy is repeated.
            if args.apply and not installer.release.is_dir():
                raise RuntimeError('Requested release is not staged.')
            installer.preflight()
        else:
            installer.preflight()
            installer.stage()
        if args.activate:
            installer.activate()
        log('Completed '+('installation' if args.apply else 'dry-run')+'; no provider login, inference, Tailscale enrollment or public ingress configured.')
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, Problem, subprocess.CalledProcessError) as exc:
        log('FAILED '+type(exc).__name__+': '+str(exc) if not isinstance(exc,subprocess.CalledProcessError) else 'FAILED command; old release/config retained unless activation switch already reported. Inspect service diagnostics; do not resume intake blindly.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
