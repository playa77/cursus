#!/usr/bin/env python3
"""Ubuntu VPS installation, revision 2026-11-20-r1. No secret output or live AI."""
import argparse
from datetime import datetime, timezone
import grp
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys


def log(message):
    print(datetime.now(timezone.utc).isoformat() + ' ' + message, flush=True)


class Installer:
    def __init__(self, args):
        self.args = args
        self.source = Path(__file__).resolve().parent.parent

    def run(self, argv, **kwargs):
        log(('PLAN ' if self.args.dry_run else 'RUN ') + ' '.join(map(str,argv)))
        if not self.args.dry_run:
            return subprocess.run(list(map(str,argv)),check=True,**kwargs)

    def account(self, name, home):
        try:
            user = pwd.getpwnam(name)
        except KeyError:
            self.run(['useradd','--system','--user-group','--create-home',
                      '--home-dir',home,'--shell','/usr/sbin/nologin',name])
            return
        if (user.pw_uid==0 or user.pw_dir!=home or user.pw_shell!='/usr/sbin/nologin'
                or grp.getgrgid(user.pw_gid).gr_name!=name):
            raise RuntimeError('Conflicting existing account: '+name)
        if any(name in group.gr_mem for group in grp.getgrall()):
            raise RuntimeError('Unexpected supplementary group on execution/service account: '+name)
        log('KEEP existing account '+name)

    def directory(self, path, mode, owner='root'):
        target = Path(path)
        if target.is_symlink():
            raise RuntimeError('Refusing directory symlink: '+path)
        if target.exists() and target.stat().st_uid != pwd.getpwnam(owner).pw_uid:
            raise RuntimeError('Conflicting existing directory owner: '+path)
        self.run(['install','-d','-m',mode,'-o',owner,'-g',owner,path])

    def copy_once(self, source, target, owner='root', mode=0o600, content=None):
        target = Path(target)
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_file():
                raise RuntimeError('Refusing unsafe existing target: '+str(target))
            log('KEEP existing configuration '+str(target))
            return
        log(('PLAN ' if self.args.dry_run else 'WRITE ') + str(target))
        if self.args.dry_run:
            return
        user = pwd.getpwnam(owner)
        # Exclusive creation prevents reruns/races from replacing operator config.
        with target.open('xb') as output:
            os.fchmod(output.fileno(),mode)
            os.fchown(output.fileno(),user.pw_uid,user.pw_gid)
            if content is None:
                with Path(source).open('rb') as incoming:
                    shutil.copyfileobj(incoming,output)
            else:
                output.write(content.encode())

    def configuration(self, role, owner):
        text = (self.source/'deploy'/f'{role}.example.toml').read_text()
        text = text.replace('"REPLACE_1_TO_4"',str(self.args.workers))
        for marker,value in [('REPLACE_RUNNER_UUID',getattr(self.args,'runner_id',None)),
            ('https://REPLACE_VPS_B.REPLACE_TAILNET.ts.net',getattr(self.args,'origin',None)),
            ('REPLACE_EXACT_TAILSCALE_LOGIN',getattr(self.args,'operator_login',None))]:
            if value:
                text = text.replace(marker,value)
        # Provider counts may differ, so do not replace their marker globally.
        for provider in ('claude','codex','agy'):
            text = text.replace(f'{provider} = "REPLACE_1_OR_2"',
                                f'{provider} = {getattr(self.args,provider)}')
        self.copy_once(None,f'/etc/cursus/{role}.toml',owner,content=text)

    def install(self):
        role = self.args.role
        accounts = ([('cursus-control','/var/lib/cursus-control')] if role=='control' else
                    [(f'cursus-{name}',f'/var/lib/cursus-identities/{name}')
                     for name in ('pi','claude','codex','agy','verifier')] +
                    [(f'cursus-exec-{i:02d}',f'/var/lib/cursus-identities/exec-{i:02d}') for i in range(1,17)])
        log(f'Preparing {role}; '+('16 pooled execution accounts' if role=='runner' else 'controller and PostgreSQL'))
        # Check known account collisions before installing packages or changing users.
        for name,home in accounts:
            try:
                user = pwd.getpwnam(name)
            except KeyError:
                continue
            if user.pw_uid==0 or user.pw_dir!=home or user.pw_shell!='/usr/sbin/nologin':
                raise RuntimeError('Conflicting existing account: '+name)
        if not self.args.skip_packages:
            self.run(['apt-get','update'])
            packages = ['python3','python3-venv','git','ca-certificates']
            packages += ['postgresql','postgresql-client'] if role=='control' else ['build-essential','util-linux']
            self.run(['apt-get','install','-y',*packages])
        if role=='runner':
            self.directory('/var/lib/cursus-identities','0711')
        for name,home in accounts:
            self.account(name,home)
            self.directory(home,'0700',name)
        self.directory('/opt/cursus','0755')
        self.directory('/opt/cursus/venv','0755')
        self.run(['python3','-m','venv','/opt/cursus/venv'])
        pip = '/opt/cursus/venv/bin/python'
        self.run([pip,'-m','pip','install','--disable-pip-version-check','--require-hashes',
                  '-r',self.source/'requirements.lock'])
        self.run([pip,'-m','pip','install','--disable-pip-version-check','--no-deps',
                  '--no-build-isolation',self.source])
        self.directory('/etc/cursus','0755')
        if role=='control':
            try:
                grp.getgrnam('cursus-operators')
            except KeyError:
                self.run(['groupadd','--system','cursus-operators'])
            self.directory('/etc/cursus/control','0700','cursus-control')
            self.directory('/var/lib/cursus-control/artifacts','0700','cursus-control')
            self.configuration(role,'cursus-control')
            self.run(['systemctl','enable','--now','postgresql'])
            sql = "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='cursus-control') THEN CREATE ROLE \"cursus-control\" LOGIN; ELSIF EXISTS (SELECT FROM pg_roles WHERE rolname='cursus-control' AND (rolsuper OR rolcreatedb OR rolcreaterole OR NOT rolcanlogin)) THEN RAISE EXCEPTION 'Conflicting existing Cursus database role'; END IF; END $$;"
            self.run(['runuser','-u','postgres','--','psql','-v','ON_ERROR_STOP=1','-c',sql])
            result = self.run(['runuser','-u','postgres','--','psql','-At','-c',
                "SELECT CASE WHEN pg_get_userbyid(datdba)='cursus-control' THEN '1' ELSE 'conflict' END FROM pg_database WHERE datname='cursus'"],capture_output=True,text=True)
            if result is not None and result.stdout.strip()=='conflict':
                raise RuntimeError('Conflicting existing Cursus database owner.')
            if result is None or result.stdout.strip()!='1':
                self.run(['runuser','-u','postgres','--','createdb','--owner=cursus-control','cursus'])
            self.copy_once(None,'/etc/cursus/control/database-dsn','cursus-control',
                content='postgresql:///cursus?host=/var/run/postgresql\n')
        else:
            self.directory('/etc/cursus/runner','0700')
            self.directory('/var/lib/cursus-runner','0711')
            for name in ('state','spool','repositories'):
                self.directory('/var/lib/cursus-runner/'+name,'0700')
            for name in ('homes','worktrees','reviews'):
                self.directory('/var/lib/cursus-runner/'+name,'0711')
            self.configuration(role,'root')
            self.copy_once(self.source/'deploy/capabilities.example.toml','/etc/cursus/runner/capabilities.toml')
        self.copy_once(self.source/f'deploy/cursus-{role}.service',
                       f'/etc/systemd/system/cursus-{role}.service',mode=0o644)
        if role=='runner':
            physical = os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')
            reserve = 2147483648
            content = '[Unit]\nDescription=Cursus aggregate execution budget\n\n[Slice]\nCPUQuota='+str(max(100,((os.cpu_count() or 1)-1)*100))+'%\nMemoryMax='+str(max(1,physical-reserve))+'\nMemorySwapMax=0\nTasksMax=2048\n'
            self.copy_once(None,'/etc/systemd/system/cursus-execution.slice',mode=0o644,content=content)
        self.run(['systemctl','daemon-reload'])
        if self.args.start:
            # Validate first; placeholders or missing credentials cannot activate.
            self.run(['runuser','-u','cursus-control','--',pip,'-c',
                "from cursus.config import load; load('control','/etc/cursus/control.toml')"] if role=='control' else
                [pip,'-c',"from cursus.config import load; load('runner','/etc/cursus/runner.toml')"])
            self.run(['systemctl','enable','--now','cursus-'+role])
        log(('Dry-run complete; no changes made. ' if self.args.dry_run else 'Installation complete. ')+
            ('Service startup requested.' if self.args.start else
             'No Cursus service was started or restarted. Complete configuration and native login before explicit activation; existing secrets were preserved.'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role',choices=('runner','control'))
    for name,maximum in [('workers',4),('claude',2),('codex',2),('agy',2)]:
        parser.add_argument('--'+name,type=int,choices=range(1,maximum+1),required=True)
    parser.add_argument('--runner-id',help='Same UUID on both hosts')
    parser.add_argument('--origin',help='Exact private HTTPS origin on both hosts')
    parser.add_argument('--operator-login',help='Exact Serve login (controller)')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--skip-packages',action='store_true')
    parser.add_argument('--start',action='store_true')
    args = parser.parse_args(argv)
    if not args.dry_run and os.geteuid()!=0:
        parser.error('Installation requires root; use --dry-run to inspect without changes.')
    try:
        Installer(args).install()
    except (OSError,RuntimeError,subprocess.CalledProcessError) as exc:
        log('FAILED: '+(str(exc) if isinstance(exc,RuntimeError) else 'Host installation step failed; check the preceding step.'))
        return 1
    return 0


if __name__=='__main__':
    sys.exit(main())
