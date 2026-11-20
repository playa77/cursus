"""Identity inventory, resource bounds and setup behavior without host mutations."""
import asyncio
from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import pwd
from tempfile import TemporaryDirectory
import tracemalloc
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from cursus.capacity import validate_capacity
from cursus.contracts import Problem
from cursus.identities import IdentityPool, prepare_home, remove_home
from cursus.journal import Journal
from cursus.resources import Resources


def capacity():
    return dict(worker=4,claude=2,codex=2,agy=2,pi=1,verifier=1,repository=1)


def accounts():
    return [dict(id=f'exec-{i:02d}',user=f'cursus-exec-{i:02d}',home=f'/fixture/exec-{i:02d}') for i in range(1,17)]


class PoolTests(unittest.TestCase):
    def test_capacity_has_independent_provider_limits(self):
        self.assertEqual(validate_capacity(capacity()),capacity())
        for field,value in [('worker',5),('worker',0),('claude',3),('codex',True),('agy',0)]:
            with self.assertRaises(Problem):
                validate_capacity(dict(capacity(),**{field:value}))
        invalid=capacity(); invalid['frontier']=1
        with self.assertRaises(Problem):
            validate_capacity(invalid)

    def test_sixteen_exclusive_durable_leases_and_explicit_release(self):
        with TemporaryDirectory() as root:
            journal=Journal(root)
            pool=IdentityPool(accounts(),journal)
            ids=[str(uuid4()) for _ in range(16)]
            chosen=[pool.acquire(identity)['user'] for identity in ids]
            self.assertEqual(len(set(chosen)),16)
            with self.assertRaises(Problem):
                pool.acquire(str(uuid4()))
            journal.close()
            journal=Journal(root)
            try:
                restored=IdentityPool(accounts(),journal)
                self.assertEqual(len(restored.held),16)
                self.assertEqual(restored.acquire(ids[0])['user'],chosen[0])
                restored.release(ids[0])
                self.assertEqual(restored.acquire(str(uuid4()))['user'],chosen[0])
                changed=accounts(); changed[0]['user']='other'
                with self.assertRaises(Problem):
                    IdentityPool(changed,journal)
            finally:
                journal.close()

    def test_private_native_auth_projection_is_allowlisted_and_disposable(self):
        with TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'native'; source.mkdir()
            (source/'auth.json').write_text('fixture-native-auth')
            (source/'unrelated').write_text('must not copy')
            user=pwd.getpwuid(os.getuid())
            attempt=str(uuid4())
            result=prepare_home(root/'homes',attempt,dict(user=user.pw_name),dict(home=str(source)),['auth.json'])
            home=Path(result['home'])
            self.assertEqual((home/'auth.json').stat().st_mode & 0o777,0o600)
            self.assertFalse((home/'unrelated').exists())
            (home/'auth.json').write_text('execution-local-state')
            self.assertEqual((source/'auth.json').read_text(),'fixture-native-auth')
            remove_home(root/'homes',attempt)
            self.assertFalse(home.exists())
            (source/'link').symlink_to(source/'auth.json')
            with self.assertRaises(Problem):
                prepare_home(root/'homes',str(uuid4()),dict(user=user.pw_name),dict(home=str(source)),['link'])

    def test_journal_loading_does_not_mirror_payload_history(self):
        with TemporaryDirectory() as root:
            journal=Journal(root)
            for i in range(160):
                journal.record('fixture',dict(index=i,text='x'*32768))
            journal.close()
            tracemalloc.start()
            journal=Journal(root)
            _,peak=tracemalloc.get_traced_memory()
            tracemalloc.stop()
            try:
                self.assertEqual(len(journal.records),161)
                self.assertLess(peak,2*1024*1024)
            finally:
                journal.close()

    def test_cgroup_command_binds_lifetime_and_all_child_resources(self):
        settings=dict(reserve_memory_bytes=1024,reserve_disk_bytes=1,worker_memory_bytes=2048,
            frontier_memory_bytes=512,verifier_memory_bytes=2048,cpu_percent=150,tasks_max=64,repository_bytes=4096)
        resource=Resources(settings,'/tmp')
        user=pwd.getpwuid(os.getuid())
        unit,command=resource.command(['/fixture/tool','literal argument'],'/tmp/path with spaces',user,
                                      {'HOME':'/tmp/private'},'worker')
        self.assertIn('--property=MemoryMax=2048',command)
        self.assertIn('--property=CPUQuota=150%',command)
        self.assertIn('--property=TasksMax=64',command)
        self.assertIn('--property=BindsTo=cursus-runner.service',command)
        self.assertEqual(command[-2:],['/fixture/tool','literal argument'])
        self.assertIn('/usr/bin/env',command)
        self.assertIn('-i',command)
        resource.total=4096
        resource.reserve('one',{'slot':'worker'})
        self.assertFalse(resource.available({'slot':'verifier'}))
        resource.release('one')
        self.assertTrue(resource.available({'slot':'verifier'}))


spec=importlib.util.spec_from_file_location('cursus_setup',Path('deploy/setup.py'))
setup=importlib.util.module_from_spec(spec); spec.loader.exec_module(setup)


class RecordingInstaller(setup.Installer):
    def __init__(self,role):
        super().__init__(SimpleNamespace(role=role,workers=4,claude=2,codex=1,agy=2,
                                        dry_run=True,skip_packages=False,start=False))
        self.commands=[]; self.created=set(); self.files={}

    def run(self,argv,**kwargs):
        self.commands.append(list(map(str,argv)))
        return SimpleNamespace(stdout='1\n')

    def account(self,name,home):
        self.created.add((name,home))

    def directory(self,*args,**kwargs):
        pass

    def copy_once(self,source,target,owner='root',mode=0o600,content=None):
        self.files.setdefault(target,content if content is not None else Path(source).read_text())


class SetupTests(unittest.TestCase):
    def test_worker_installs_exact_pool_and_preserves_config_on_rerun(self):
        installer=RecordingInstaller('runner')
        installer.install()
        pool={name for name,_ in installer.created if name.startswith('cursus-exec-')}
        self.assertEqual(pool,{f'cursus-exec-{i:02d}' for i in range(1,17)})
        import tomllib
        config=tomllib.loads(installer.files['/etc/cursus/runner.toml'])
        self.assertEqual(config['capacity']['worker'],4)
        self.assertEqual(config['capacity']['codex'],1)
        self.assertEqual(len(config['execution_pool']),16)
        installer.files['/etc/cursus/runner.toml']='existing operator configuration'
        installer.install()
        self.assertEqual(installer.files['/etc/cursus/runner.toml'],'existing operator configuration')
        self.assertFalse(any('cursus-runner' in c and 'enable' in c for c in installer.commands))

    def test_controller_installs_database_and_never_execution_accounts(self):
        installer=RecordingInstaller('control'); installer.install()
        self.assertEqual(installer.created,{('cursus-control','/var/lib/cursus-control')})
        self.assertIn('/etc/cursus/control/database-dsn',installer.files)
        self.assertTrue(any('postgresql' in c for c in installer.commands))

    def test_real_copy_once_keeps_existing_and_rejects_symlinks(self):
        with TemporaryDirectory() as root:
            args=SimpleNamespace(dry_run=False)
            installer=setup.Installer(args)
            target=Path(root)/'config'
            user=pwd.getpwuid(os.getuid()).pw_name
            installer.copy_once(None,target,user,content='first')
            installer.copy_once(None,target,user,content='second')
            self.assertEqual(target.read_text(),'first')
            link=Path(root)/'link'; link.symlink_to(target)
            with self.assertRaises(RuntimeError):
                installer.copy_once(None,link,user,content='third')

    def test_conflicting_account_is_rejected_without_adoption(self):
        installer=setup.Installer(SimpleNamespace(dry_run=True))
        fake=SimpleNamespace(pw_uid=0,pw_dir='/fixture',pw_shell='/bin/bash',pw_gid=0)
        with patch.object(setup.pwd,'getpwnam',return_value=fake):
            with self.assertRaises(RuntimeError):
                installer.account('cursus-exec-01','/var/lib/cursus-identities/exec-01')


class RunnerConfigurationTests(unittest.TestCase):
    def test_new_runner_configuration_and_pool_validation(self):
        import tomllib
        from hashlib import sha256
        from cursus.config import load
        with TemporaryDirectory() as root:
            root=Path(root)
            bearer=root/'bearer'; bearer.write_text('fixture-token'); bearer.chmod(0o600)
            text=Path('deploy/runner.example.toml').read_text().replace('"REPLACE_1_TO_4"','4').replace('"REPLACE_1_OR_2"','2')
            text=text.replace('REPLACE_RUNNER_UUID',str(uuid4())).replace('https://REPLACE_VPS_B.REPLACE_TAILNET.ts.net','https://fixture.ts.net')
            text=text.replace('/etc/cursus/runner/bearer',str(bearer))
            text=text.replace('/etc/cursus/runner/capabilities.toml',str(root/'caps.toml'))
            parsed=tomllib.loads(text)
            profile='qualification = "qualified"\n'
            for cli,identity in parsed['cli'].items():
                profile+=f'\n[{cli}]\n'
                for key in ('binary','user','home'):
                    import json
                    profile+=key+' = '+json.dumps(identity[key])+'\n'
            (root/'caps.toml').write_text(profile)
            text=text.replace('REPLACE_SHA256_OF_QUALIFIED_PROFILE',sha256(profile.encode()).hexdigest())
            config=root/'runner.toml'; config.write_text(text)
            value=load('runner',str(config))
            self.assertEqual(len(value['execution_pool']),16)
            self.assertEqual(value['capacity']['worker'],4)
            self.assertEqual(value['capacity']['claude'],2)
            config.write_text(text.replace('cursus-exec-02','cursus-exec-01'))
            with self.assertRaises(Problem):
                load('runner',str(config))


class CgroupStopTests(unittest.IsolatedAsyncioTestCase):
    async def test_supervisor_failure_never_proves_process_stop(self):
        from unittest.mock import AsyncMock
        settings=dict(reserve_memory_bytes=1,reserve_disk_bytes=1,worker_memory_bytes=1,
            frontier_memory_bytes=1,verifier_memory_bytes=1,cpu_percent=100,tasks_max=1,repository_bytes=1)
        resources=Resources(settings,'/tmp')
        stop=SimpleNamespace(wait=AsyncMock(return_value=0),returncode=0)
        query=SimpleNamespace(communicate=AsyncMock(return_value=(b'',b'failed')),returncode=1)
        with patch('cursus.resources.asyncio.create_subprocess_exec',AsyncMock(side_effect=[stop,query])):
            with self.assertRaises(Problem) as caught:
                await resources.stop('cursus-task-fixture.service')
            self.assertEqual(caught.exception.code,'unknown_stop')
        query=SimpleNamespace(communicate=AsyncMock(return_value=(b'inactive\n',b'')),returncode=0)
        with patch('cursus.resources.asyncio.create_subprocess_exec',AsyncMock(side_effect=[stop,query])):
            await resources.stop('cursus-task-fixture.service')

    async def test_native_environment_does_not_inherit_manager_defaults(self):
        import subprocess
        import sys
        settings=dict(reserve_memory_bytes=1,reserve_disk_bytes=1,worker_memory_bytes=1,
            frontier_memory_bytes=1,verifier_memory_bytes=1,cpu_percent=100,tasks_max=1,repository_bytes=1)
        resources=Resources(settings,'/tmp')
        user=pwd.getpwuid(os.getuid())
        _,command=resources.command([sys.executable,'-c',
            "import os; assert 'CURSUS_MANAGER_SECRET' not in os.environ; assert os.environ['HOME']=='/tmp/fixture-home'"],
            '/tmp',user,{'HOME':'/tmp/fixture-home','PATH':'/usr/bin:/bin'},'frontier')
        # Emulate only the external systemd launch boundary; execute the exact
        # native env/argv tail, including the production env -i protection.
        subprocess.run(command[command.index('--')+1:],env={'CURSUS_MANAGER_SECRET':'fixture'},
                       capture_output=True,timeout=5,check=True)
