"""Fresh-shell installer contracts; no network, package manager or host changes."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def helper():
    spec = importlib.util.spec_from_file_location('cursus_install_guide',ROOT/'deploy/install.py')
    module = importlib.util.module_from_spec(spec)
    with patch.object(sys,'path',[str(ROOT/'deploy'),*sys.path]):
        spec.loader.exec_module(module)
    return module


class EntrypointTests(unittest.TestCase):
    def test_help_and_dry_run_from_empty_home_have_no_side_effects(self):
        with tempfile.TemporaryDirectory(prefix='cursus fresh — ') as folder:
            home = Path(folder)
            for args in (['--help'],['--host','controller','--dry-run'],['--host','worker','--dry-run']):
                result = subprocess.run(['bash',str(ROOT/'install.sh'),*args],cwd=home,
                                        env={**os.environ,'HOME':folder},text=True,capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(list(home.iterdir()),[])

    def test_missing_values_and_unattended_inputs_fail_before_host_changes(self):
        for args in (['--config'],['--host','nope'],['--non-interactive','--yes'],
                     ['--dry-run','--stage-only','--activate-existing']):
            result = subprocess.run(['bash',str(ROOT/'install.sh'),*args],text=True,capture_output=True)
            self.assertEqual(result.returncode,2,result.stdout+result.stderr)

    def test_piped_bootstrap_obtains_source_and_preserves_argument_boundaries(self):
        with tempfile.TemporaryDirectory(prefix='cursus empty home — ') as folder:
            root = Path(folder)
            bin_dir = root/'mock-bin'; bin_dir.mkdir()
            log = root/'calls.jsonl'
            os_release = root/'os-release'; os_release.write_text('ID=ubuntu\nVERSION_ID="26.04"\n')
            # Replace only the OS boundary. All host mutators are executable
            # stand-ins; exercise the actual piped shell and its source handling.
            script = (ROOT/'install.sh').read_text().replace('/etc/os-release',json.dumps(str(os_release),ensure_ascii=False))
            mock = f'''#!{sys.executable}
import json,os,sys
from pathlib import Path
name=Path(sys.argv[0]).name
with open({str(log)!r},'a') as out: out.write(json.dumps([name,*sys.argv[1:]])+'\\n')
if name=='sudo':
    if sys.argv[1:] == ['-v']: sys.exit(0)
    os.execvp(sys.argv[1],sys.argv[1:])
if name=='git' and 'rev-parse' in sys.argv: print('a'*40)
if name=='git' and 'clone' in sys.argv:
    source=Path(sys.argv[-1]); (source/'.git').mkdir(parents=True)
    (source/'deploy').mkdir(); (source/'deploy/install.py').write_text('# mocked helper')
'''
            for name in ('sudo','apt-get','git','env'):
                path=bin_dir/name; path.write_text(mock); path.chmod(0o755)
            source=root/'source dir — fresh'
            config=root/'private config.toml'; config.write_text('schema_version = 2\n')
            argv=['bash','-s','--','--host','controller','--non-interactive','--yes',
                  '--source-dir',str(source),'--config',str(config)]
            result=subprocess.run(argv,input=script,cwd=root,text=True,capture_output=True,
                                  env={**os.environ,'HOME':folder,'PATH':str(bin_dir)+':/usr/bin:/bin'})
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            calls=[json.loads(line) for line in log.read_text().splitlines()]
            clone=next(call for call in calls if call[0]=='git' and 'clone' in call)
            self.assertEqual(clone[-1],str(source))
            invocation=next(call for call in calls if call[0]=='env')
            self.assertIn(str(source/'deploy/install.py'),invocation)
            self.assertEqual(invocation[invocation.index('--config')+1],str(config))
            self.assertIn('-i',invocation)
            self.assertNotIn('API_KEY',' '.join(invocation))
            marker=source/'preserve.txt'; marker.write_text('existing operator work')
            again=subprocess.run(argv,input=script,cwd=root,text=True,capture_output=True,
                                 env={**os.environ,'HOME':folder,'PATH':str(bin_dir)+':/usr/bin:/bin'})
            self.assertEqual(again.returncode,0,again.stdout+again.stderr)
            calls=[json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(sum(call[0]=='git' and 'clone' in call for call in calls),1)
            self.assertEqual(marker.read_text(),'existing operator work')


class GuideContracts(unittest.TestCase):
    def test_fresh_worker_has_no_repository_or_work_questions(self):
        import pwd
        import tomllib
        from types import SimpleNamespace
        module = helper()
        guide = module.Guide(SimpleNamespace(source=str(ROOT),host='worker',non_interactive=True))
        guide.user = pwd.getpwuid(os.getuid()).pw_name
        guide.controller_origin = lambda: 'https://controller.example.ts.net'
        guide.resource_summary = lambda: None
        guide.hardware = dict(total=12288,available=11000,cpu=6,free=100000)
        import io
        guide.tty = io.StringIO()
        questions = []
        def ask(question, default=None):
            questions.append(question)
            if default is not None:
                return str(default)
            self.assertTrue(question.startswith('Setting: capacity.'), question)
            return '1'
        guide.ask = ask
        real_write = module.write_private
        with tempfile.TemporaryDirectory() as folder:
            guide.root = Path(folder)
            def write(path, data, user=None):
                if str(path).startswith('/etc/cursus/runner/capabilities-'):
                    path = guide.root/'capabilities.toml'
                return real_write(path, data, user)
            with patch.object(sys,'path',[str(ROOT/'deploy'),*sys.path]):
                import native_setup
                with patch.object(native_setup,'NativeSetup',return_value=SimpleNamespace(run=lambda:None)), patch.object(module,'write_private',side_effect=write), patch.object(subprocess,'check_output',return_value='podman version 5.7.0'), patch.object(guide,'tailscale',return_value={}):
                    path = guide.configure()
            self.assertIsNone(path)
            pending=guide.root/'runner.pending.toml'
            config = tomllib.loads(pending.read_text())
            self.assertFalse((guide.root/'runner.toml').exists())
            self.assertEqual(config['repositories'], [])
            self.assertTrue(questions)
            self.assertEqual(pending.stat().st_mode & 0o777,0o600)

    def test_saved_pending_installation_is_reused_without_questions_or_activation(self):
        from types import SimpleNamespace
        import pwd
        module=helper()
        guide=module.Guide(SimpleNamespace(source=str(ROOT),host='worker',non_interactive=True))
        guide.user=pwd.getpwuid(os.getuid()).pw_name
        guide.ask=lambda *args:self.fail('Pending installation must not prompt for login or choices again')
        config={'containers':{'image':'sha256:'+'a'*64}}
        with tempfile.TemporaryDirectory() as folder:
            guide.root=Path(folder)
            guide.native_install_complete(config)
            pending=guide.root/'runner.pending.toml'
            original=pending.read_bytes()
            with patch.object(sys,'path',[str(ROOT/'deploy'),*sys.path]):
                import native_setup
                with patch.object(native_setup,'NativeSetup',return_value=SimpleNamespace(run=lambda:None)):
                    self.assertIsNone(guide.configure())
            self.assertEqual(pending.read_bytes(),original)
            self.assertFalse((guide.root/'runner.toml').exists())

    def test_native_installation_completion_does_not_continue_into_deployment(self):
        from types import SimpleNamespace
        module=helper()
        guide=module.Guide(SimpleNamespace(source=str(ROOT),host='worker',non_interactive=True,
            config=None,wheelhouse=None,activate_existing=False,native_only=False))
        with patch.object(module.os,'geteuid',return_value=0), patch.object(Path,'read_text',return_value='ID=ubuntu\nVERSION_ID="26.04"\n'), patch.object(module,'clean_checkout',return_value='a'*40), patch.object(module,'Installer') as installer, patch.object(guide,'configure',return_value=None), patch.object(guide,'secrets',side_effect=AssertionError('No pairing or credentials after installation')):
            guide.run()
        installer.return_value.stage.assert_not_called()
        installer.return_value.activate.assert_not_called()

    def test_idle_worker_pairs_without_github_credentials(self):
        import contextlib
        import io
        import pwd
        from types import SimpleNamespace
        module = helper()
        guide = module.Guide(SimpleNamespace(source=str(ROOT),host='worker',non_interactive=True))
        guide.user = pwd.getpwuid(os.getuid()).pw_name
        guide.ask = lambda *args: self.fail('Idle installation must not ask for credentials')
        guide._tailscale = {'Self':{'DNSName':'worker.example.ts.net.'}}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = root/'capabilities.toml'; profile.write_text('fixture = "offline"\n')
            bearer = root/'bearer'
            publisher = dict(git_credential_file=str(root/'git-token'),github_credential_file=str(root/'api-token'))
            config = dict(service=dict(bearer_file=str(bearer),capabilities_file=str(profile),
                                      runner_id='fixture-id',origin='https://controller.example.ts.net'),
                          repositories=[],capacity={},publisher=publisher)
            output = io.StringIO()
            with patch.object(sys,'path',[str(ROOT/'deploy'),*sys.path]), contextlib.redirect_stdout(output), patch.object(module.getpass,'getpass',side_effect=AssertionError('Unexpected token prompt')):
                guide.secrets(config)
                import native_setup
                paired = native_setup.read_pairing(output.getvalue().splitlines()[-1])
            self.assertEqual(paired['config']['repositories'],[])
            self.assertEqual(paired['config']['service']['tailnet_node'],'worker.example.ts.net')
            self.assertTrue(bearer.is_file())
            for path in publisher.values(): self.assertFalse(Path(path).exists())
            config['repositories'] = [{'owner':'fixture','name':'repo'}]
            with patch.object(sys,'path',[str(ROOT/'deploy'),*sys.path]), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError,'Publisher credential files missing'): guide.secrets(config)

    def test_saved_configuration_is_preserved_including_existing_enrollment(self):
        from types import SimpleNamespace
        module = helper()
        guide = module.Guide(SimpleNamespace(source=str(ROOT),host='worker',non_interactive=True))
        with tempfile.TemporaryDirectory() as folder:
            guide.root = Path(folder)
            path = guide.root/'runner.toml'
            original = (ROOT/'deploy/runner.example.toml').read_bytes()
            path.write_bytes(original)
            self.assertEqual(guide.configure(),path)
            self.assertEqual(path.read_bytes(),original)

    def test_config_writer_roundtrips_all_shipped_shapes(self):
        import tomllib
        guide=helper()
        for path in [*ROOT.glob('deploy/*.example.toml'),ROOT/'roles.toml']:
            value=tomllib.loads(path.read_text())
            self.assertEqual(tomllib.loads(guide.toml_text(value)),value,path)

    def test_private_creation_preserves_existing_files_and_rejects_symlinks(self):
        guide=helper()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); path=root/'private'
            guide.write_private(path,'fixture-only')
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            with self.assertRaises(FileExistsError): guide.write_private(path,'replacement')
            link=root/'link'; link.symlink_to(path)
            with self.assertRaises(FileExistsError): guide.write_private(link,'replacement')
            self.assertEqual(path.read_text(),'fixture-only')

    def test_dirty_source_is_refused_without_discarding_work(self):
        guide=helper()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            subprocess.run(['git','init','--quiet',folder],check=True)
            (root/'keep.txt').write_text('operator work')
            with self.assertRaisesRegex(RuntimeError,'never reset'): guide.clean_checkout(root)
            self.assertEqual((root/'keep.txt').read_text(),'operator work')

    def test_guided_role_release_is_readable_pinned_and_does_not_modify_source(self):
        from types import SimpleNamespace
        import tomllib
        from cursus.config import role_release
        guide_module=helper()
        guide=guide_module.Guide(SimpleNamespace(source=str(ROOT),host='controller',non_interactive=True))
        registry=tomllib.loads((ROOT/'roles.toml').read_text())
        profiles={}
        for name,role in registry['roles'].items():
            cli=role['cli']
            if cli not in profiles:
                profiles[cli]=dict(model='fixture-model',reasoning='fixture-reasoning',qualified_roles=[],
                                   tool_allowlist=role['tools'],role_profiles={})
            profiles[cli]['qualified_roles'].append(name)
            profiles[cli]['role_profiles'][name]=dict(qualified_roles=[name],tool_allowlist=role['tools'])
            if cli=='pi': profiles[cli]['provider']='fixture-go'
        original=(ROOT/'roles.toml').read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            guide.root=Path(folder)
            root,commit=guide.roles(b'fixture profile bytes',profiles)
            service=dict(roles_file=str(root/'roles.toml'),prompts_root=str(root/'prompts'),role_release_commit=commit)
            loaded=role_release(service)
            self.assertEqual(set(loaded['roles']),set(registry['roles']))
            self.assertEqual(root.stat().st_mode & 0o777,0o755)
            self.assertEqual(guide.roles(b'fixture profile bytes',profiles),(root,commit))
            self.assertEqual((ROOT/'roles.toml').read_bytes(),original)

    def test_missing_or_exposed_auth_domain_blocks_activation(self):
        from types import SimpleNamespace
        import pwd
        guide=helper().Guide(SimpleNamespace(source=str(ROOT),host='worker',non_interactive=True))
        guide.user=pwd.getpwuid(os.getuid()).pw_name
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'domain'
            config={'containers':{'credentials':{'pi':[{'mounts':[{'source':str(path)}]}]}}}
            with self.assertRaisesRegex(RuntimeError,'prerequisite missing'): guide.require_native_mounts(config)
            path.mkdir(mode=0o755)
            with self.assertRaisesRegex(RuntimeError,'private'): guide.require_native_mounts(config)
            path.chmod(0o700)
            guide.require_native_mounts(config)

    def test_terminal_questions_work_on_a_nonseekable_tty(self):
        import builtins
        import pty
        master,slave=pty.openpty()
        terminal=None
        real_open=builtins.open
        def tty_open(path,*args,**kwargs):
            return real_open(os.ttyname(slave) if str(path)=='/dev/tty' else path,*args,**kwargs)
        try:
            module=helper()
            with patch('builtins.open',side_effect=tty_open): terminal=module.Terminal()
            terminal.write('Host? '); terminal.flush()
            os.write(master,b'controller\n')
            self.assertEqual(terminal.readline(),'controller\n')
            self.assertIn(b'Host?',os.read(master,1024))
        finally:
            if terminal:
                terminal.reader.close(); terminal.writer.close()
            os.close(master); os.close(slave)

class SourceRefTests(unittest.TestCase):
    def test_bootstrap_checks_out_remote_branch_absent_from_local_heads(self):
        with tempfile.TemporaryDirectory(prefix='cursus branch — ') as folder:
            root=Path(folder);repo=root/'origin';repo.mkdir()
            def git(*args):
                return subprocess.run(['/usr/bin/git','-C',str(repo),*args],check=True,capture_output=True,text=True)
            git('init','--quiet','--initial-branch=main')
            (repo/'README').write_text('fixture')
            git('add','README')
            git('-c','user.name=Fixture','-c','user.email=fixture@localhost','commit','--quiet','-m','base')
            git('checkout','-b','codex/native-fixture')
            (repo/'deploy').mkdir();(repo/'deploy/install.py').write_text('# fixture helper')
            git('add','deploy/install.py')
            git('-c','user.name=Fixture','-c','user.email=fixture@localhost','commit','--quiet','-m','installer')
            wanted=git('rev-parse','HEAD').stdout.strip()
            git('checkout','main')
            bin_dir=root/'bin';bin_dir.mkdir()
            wrapper=f'''#!{sys.executable}
import os,sys
from pathlib import Path
name=Path(sys.argv[0]).name
if name=='sudo':
    if sys.argv[1:]==['-v']:sys.exit(0)
    os.execvp(sys.argv[1],sys.argv[1:])
if name=='git':
    args=[{str(repo)!r} if value=='https://github.com/playa77/cursus.git' else value for value in sys.argv[1:]]
    os.execv('/usr/bin/git',['git',*args])
'''
            for name in ('sudo','git','apt-get','env'):
                path=bin_dir/name;path.write_text(wrapper);path.chmod(0o755)
            os_release=root/'os-release';os_release.write_text('ID=ubuntu\nVERSION_ID="26.04"\n')
            script=(ROOT/'install.sh').read_text().replace('/etc/os-release',json.dumps(str(os_release),ensure_ascii=False))
            target=root/'fresh source'
            result=subprocess.run(['bash','-s','--','--host','worker','--yes','--non-interactive',
                                   '--config',str(root/'unused-fixture-config'),'--source-dir',str(target),
                                   '--ref','codex/native-fixture'],input=script,text=True,capture_output=True,
                                  cwd=root,env={**os.environ,'HOME':folder,'PATH':str(bin_dir)+':/usr/bin:/bin'})
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            actual=subprocess.check_output(['/usr/bin/git','-C',str(target),'rev-parse','HEAD'],text=True).strip()
            self.assertEqual(actual,wanted)
            self.assertTrue((target/'deploy/install.py').exists())

            # Simulate the operator's prior installer checkout: main does not
            # contain the new helper, but the downloaded entry point does.
            default=root/'cursus-source'
            subprocess.run(['/usr/bin/git','clone',str(repo),str(default)],check=True,capture_output=True)
            base=subprocess.check_output(['/usr/bin/git','-C',str(default),'rev-parse','HEAD'],text=True).strip()
            arguments=['bash','-s','--','--host','worker','--yes','--non-interactive',
                       '--config',str(root/'unused-fixture-config'),'--ref','codex/native-fixture']
            environment={**os.environ,'HOME':folder,'PATH':str(bin_dir)+':/usr/bin:/bin'}
            updated=subprocess.run(arguments,input=script,text=True,capture_output=True,cwd=root,env=environment)
            self.assertEqual(updated.returncode,0,updated.stdout+updated.stderr)
            self.assertEqual(subprocess.check_output(['/usr/bin/git','-C',str(default),'rev-parse','HEAD'],text=True).strip(),wanted)
            subprocess.run(['/usr/bin/git','-C',str(default),'checkout','main'],check=True,capture_output=True)
            (default/'keep.txt').write_text('operator work')
            preserved=subprocess.run(arguments,input=script,text=True,capture_output=True,cwd=root,env=environment)
            self.assertEqual(preserved.returncode,0,preserved.stdout+preserved.stderr)
            self.assertEqual((default/'keep.txt').read_text(),'operator work')
            self.assertEqual(subprocess.check_output(['/usr/bin/git','-C',str(default),'rev-parse','HEAD'],text=True).strip(),base)
            fresh=list(root.glob('cursus-installer.*/source'))
            self.assertEqual(len(fresh),1)
            self.assertTrue((fresh[0]/'deploy/install.py').exists())

class DiscoveryContracts(unittest.TestCase):
    def guide(self):
        from types import SimpleNamespace
        return helper().Guide(SimpleNamespace(source=str(ROOT),host='worker',non_interactive=True))

    def test_status_is_bounded_cached_and_peer_role_is_selected(self):
        from types import SimpleNamespace
        guide = self.guide()
        status = dict(BackendState='Running',Self={'DNSName':'worker.example.ts.net.'},
                      Peer={'b':{'DNSName':'controller.example.ts.net.'}},
                      User={'1':{'LoginName':'operator@example.com'}})
        with patch.object(subprocess,'run',return_value=SimpleNamespace(stdout=json.dumps(status))) as run:
            guide.ask=lambda *args:'1'
            self.assertEqual(guide.controller_origin(),'https://controller.example.ts.net')
            self.assertEqual(guide.operator_login(),'operator@example.com')
            self.assertEqual(guide.node_name(guide.tailscale()['Self']),'worker.example.ts.net')
            run.assert_called_once_with(['tailscale','status','--json'],check=True,capture_output=True,text=True,timeout=15)

    def test_discovery_failures_do_not_request_manual_facts(self):
        from types import SimpleNamespace
        for output in ('{}','not json',json.dumps({'BackendState':'NeedsLogin'})):
            guide=self.guide()
            with patch.object(subprocess,'run',return_value=SimpleNamespace(stdout=output)):
                with self.assertRaises(RuntimeError): guide.tailscale()
        guide=self.guide()
        with patch.object(subprocess,'run',side_effect=FileNotFoundError):
            with self.assertRaisesRegex(RuntimeError,'No manual URL'):guide.tailscale()

    def test_operator_choice_does_not_assume_machine_owner(self):
        guide=self.guide()
        guide._tailscale={'User':{'1':{'LoginName':'machine-owner@example.com'},'2':{'LoginName':'website-operator@example.com'}}}
        guide.ask=lambda *args:'2'
        self.assertEqual(guide.operator_login(),'website-operator@example.com')

    def test_invalid_dns_and_missing_peers_fail_without_guessing(self):
        guide=self.guide()
        for name in ('','controller/bad','https://controller.example.ts.net'):
            with self.assertRaises(RuntimeError):guide.node_name({'DNSName':name})
        guide._tailscale={'Peer':{}}
        with self.assertRaisesRegex(RuntimeError,'No candidates'):guide.controller_origin()


class ResourcePromptContracts(unittest.TestCase):
    def guide(self, answers='\n'*30, total=12288, available=11000, cpu=6, free=100000):
        from types import SimpleNamespace
        import io
        guide=helper().Guide(SimpleNamespace(source=str(ROOT),host='worker',non_interactive=True))
        reader=io.StringIO(answers)
        output=io.StringIO()
        guide.tty=SimpleNamespace(write=output.write,flush=output.flush,readline=reader.readline)
        guide.hardware=dict(total=total,available=available,cpu=cpu,free=free)
        guide.session_ceilings=dict(worker=4,claude=2,codex=2,agy=2)
        return guide,output

    def config(self):
        import tomllib
        containers=tomllib.loads((ROOT/'deploy/runner.example.toml').read_text())['containers']
        containers['image']='fixture-image'
        containers['version']='5.0'
        containers['credentials']={}
        return {'containers':containers}

    def test_enter_accepts_a_coherent_plan_and_explains_each_scope(self):
        guide,output=self.guide()
        config=guide.fill(self.config())['containers']
        budget=config['budget']; agent=config['resources']['agent']; verifier=config['resources']['verifier']
        self.assertLessEqual(budget['memory_mb']+budget['host_reserve_mb'],12288)
        self.assertLessEqual(budget['cpu_millis']+budget['host_reserve_cpu_millis'],6000)
        for key in ('memory_mb','cpu_millis','pids'):
            self.assertLessEqual(agent[key]+verifier[key],budget[key])
        for resource in (agent,verifier):
            self.assertLess(resource['tmp_mb']+resource['home_mb'],resource['memory_mb'])
        self.assertGreater(config['disk_reserve_mb'],0)
        self.assertLess(config['disk_reserve_mb'],100000)
        text=output.getvalue()
        self.assertIn('ALL running containers',text)
        self.assertIn('agents share',text)
        self.assertIn('pi 4',text)
        self.assertIn('existing containers keep running',text)
        self.assertIn('Suggested:',text)
        self.assertNotIn('Under containers.budget',text)
        self.assertNotIn('at most 1 agent',text)
        self.assertGreater(agent['memory_mb'],budget['memory_mb']//2)
        self.assertEqual(budget['pids'],11264)

    def test_custom_reserves_change_later_suggestions(self):
        guide,_=self.guide('4096\n1500\n'+'\n'*30)
        config=guide.fill(self.config())['containers']
        self.assertEqual(config['budget']['host_reserve_mb'],4096)
        self.assertEqual(config['budget']['host_reserve_cpu_millis'],1500)
        self.assertLessEqual(config['budget']['memory_mb'],6904)
        self.assertEqual(config['budget']['cpu_millis'],4500)

    def test_bad_numbers_retry_without_losing_previous_answers(self):
        guide,output=self.guide('abc\n-1\n0\n999999\n2048\n'+'\n'*30)
        config=guide.fill(self.config())['containers']
        self.assertEqual(config['budget']['host_reserve_mb'],2048)
        self.assertGreaterEqual(output.getvalue().count('Enter a whole number'),4)

    def test_small_and_large_hosts_get_valid_supported_plans(self):
        for total,available,cpu,free in ((2048,1800,1,3000),(65536,60000,32,1000000)):
            guide,_=self.guide(total=total,available=available,cpu=cpu,free=free)
            config=guide.fill(self.config())['containers']; budget=config['budget']
            self.assertLessEqual(budget['memory_mb']+budget['host_reserve_mb'],min(total,12288))
            self.assertLessEqual(budget['cpu_millis']+budget['host_reserve_cpu_millis'],min(cpu*1000,6000))
            self.assertLess(config['disk_reserve_mb'],free)
            for resource in config['resources'].values():
                self.assertLess(resource['tmp_mb']+resource['home_mb'],resource['memory_mb'])

    def test_shared_agent_maximum_is_not_divided_by_session_count(self):
        guide,_=self.guide()
        config=guide.fill(self.config())['containers']
        self.assertEqual(config['resources']['agent']['memory_mb'],6937)
        self.assertEqual(config['resources']['verifier']['memory_mb'],991)
        self.assertEqual(config['resources']['agent']['pids'],10240)

    def test_invalid_preset_limit_fails_with_context_without_overwriting_it(self):
        guide,_=self.guide()
        config=self.config()
        config['containers']['resources']['verifier']['memory_mb']=999999
        with self.assertRaisesRegex(RuntimeError,'verifier'):
            guide.fill(config)
        self.assertEqual(config['containers']['resources']['verifier']['memory_mb'],999999)
