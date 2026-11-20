"""Native setup contracts and real local RPC framing; no provider calls/logins."""
from contextlib import contextmanager
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]


def module(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


class NativeSetupTests(unittest.TestCase):
    def native(self):return module('deploy/native_setup.py','native_setup_fixture')

    def test_all_generated_profiles_match_runtime_contract_and_scout_mapping(self):
        from cursus.config import capability
        native=self.native()
        manifest={'packages':{cli:dict(binary_digest='a'*64,observed_version='fixture-1.0') for cli in native.CLIS}}
        ceilings=dict(worker=2,claude=1,codex=1,agy=1,verifier=1,repository=1)
        profile=native.profiles(manifest,'sha256:'+'b'*64,{cli:'fixture-model' for cli in native.CLIS},'fixture-go',ceilings)
        self.assertEqual(profile['qualification'],'unqualified')
        for cli in native.CLIS:
            profile[cli]['probe_evidence']=['fixture-only']
            capability(cli,profile[cli])
        scout={**profile['pi'],**profile['pi']['role_profiles']['scout']}
        self.assertEqual(scout['tool_allowlist'],['read','list','search'])
        self.assertNotIn('bash',','.join(scout['read_only_argv']))
        self.assertEqual(profile['pi']['credential_concurrency'],2)

    def test_pairing_roundtrip_and_size_limit(self):
        native=self.native()
        bundle=dict(format=1,config={'capacity':{'worker':2}},profile='fixture-profile',bearer_digest='a'*64)
        code=native.pairing_code(bundle)
        self.assertEqual(native.read_pairing(code),bundle)
        with self.assertRaises(ValueError):native.read_pairing('x'*65537)
        with self.assertRaises(ValueError):native.read_pairing(native.pairing_code({**bundle,'secret':'not permitted'}))

    def test_login_opens_all_four_native_installations_with_tty(self):
        native=self.native();manager=native.NativeSetup.__new__(native.NativeSetup)
        writer=io.StringIO();reader=io.StringIO()
        manager.guide=SimpleNamespace(tty=SimpleNamespace(reader=reader,writer=writer,write=writer.write,flush=writer.flush),ask=lambda *a:'login')
        calls=[]
        @contextmanager
        def session(image,domain):
            calls.append(('domain',domain['id']));yield 'owned-container'
        manager.session=session
        manager.podman=lambda *argv,**kw:calls.append((argv,kw))
        manager.login('sha256:'+'a'*64,{cli:[{'id':cli+'-1'}] for cli in native.CLIS})
        commands=[call[0] for call in calls if isinstance(call[0],tuple)]
        self.assertEqual({args[4] for args in commands},{'claude','codex','agy','pi'})
        self.assertTrue(all(args[:3]==('exec','--interactive','--tty') for args in commands))
        self.assertIn(('exec','--interactive','--tty','owned-container','codex','login','--device-auth'),commands)
        self.assertIn('/login',writer.getvalue())

    def test_rpc_probe_keeps_input_open_until_terminal_event(self):
        native=self.native();manager=native.NativeSetup.__new__(native.NativeSetup)
        with tempfile.TemporaryDirectory() as folder:
            fixture=Path(folder)/'rpc.py'
            fixture.write_text('''import json,sys
request=json.loads(sys.stdin.readline())
assert request['type']=='prompt'
print(json.dumps({'type':'response','id':request['id'],'success':True}),flush=True)
print(json.dumps({'type':'message_end','message':{'role':'assistant','content':[{'type':'text','text':'{"cursus_native_login":"ok"}'}]}}),flush=True)
print(json.dumps({'type':'agent_end'}),flush=True)
assert sys.stdin.read()==''
''')
            manager.prefix=[sys.executable,str(fixture)]
            output=manager.probe('fixture',[],b'{"type":"prompt","id":"test"}\n',True)
            from cursus.execution import Execution
            self.assertEqual(Execution({}, {}, {},allow_test_identity=True).normalize('pi',output),{'cursus_native_login':'ok'})

    def test_antigravity_native_result_and_failure_are_not_claude_shaped(self):
        from cursus.execution import Execution
        from cursus.contracts import Problem
        execution=Execution({}, {}, {},allow_test_identity=True)
        frame={'event':'result','result':{'status':'SUCCESS','response':'{"native":"ok"}'}}
        self.assertEqual(execution.normalize('agy',json.dumps(frame).encode()),{'native':'ok'})
        frame['result']['status']='ERROR'
        with self.assertRaises(Problem):execution.normalize('agy',json.dumps(frame).encode())

    def test_project_customizations_are_masked_without_modifying_repository(self):
        from cursus.containers import customization_masks
        from cursus.contracts import Problem
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'.agents').mkdir();(root/'.agents/hook').write_text('fixture')
            (root/'AGENTS.md').write_text('Keep textual instructions')
            (root/'sub').mkdir();(root/'sub/.mcp.json').write_text('{}')
            masks=customization_masks(root)
            self.assertTrue(any('/workspace/.agents:' in x for x in masks))
            self.assertIn('/dev/null:/workspace/sub/.mcp.json:ro',masks)
            self.assertFalse(any('AGENTS.md' in x for x in masks))
            self.assertEqual((root/'.agents/hook').read_text(),'fixture')
            (root/'.codex').symlink_to(root/'sub',target_is_directory=True)
            with self.assertRaises(Problem):customization_masks(root)

    def test_native_image_installation_resolves_and_records_all_four_tools(self):
        installer=module('deploy/native/install-tools.py','native_image_install_fixture')
        payload=io.BytesIO()
        with tarfile.open(fileobj=payload,mode='w:gz') as archive:
            item=tarfile.TarInfo('antigravity');data=b'fixture-native';item.size=len(data);archive.addfile(item,io.BytesIO(data))
        artifact=payload.getvalue()
        metadata=dict(url='https://fixture.invalid/native.tar.gz',sha512=hashlib.sha512(artifact).hexdigest(),version='fixture-agy')
        with tempfile.TemporaryDirectory() as folder:
            installer.PREFIX=Path(folder);(installer.PREFIX/'bin').mkdir()
            installs=[]
            def output(argv,**kw):
                if argv==['node','--version']:return 'v24.0.0'
                if argv[:2]==['npm','view']:return '"1.2.3"'
                return 'fixture version'
            def run(argv,**kw):
                cli=next(cli for cli,pkg in installer.PACKAGES.items() if pkg+'@1.2.3' in argv)
                installs.append(cli);(installer.PREFIX/'bin'/cli).write_bytes(('fixture-'+cli).encode())
                return SimpleNamespace(returncode=0)
            with patch.object(installer.subprocess,'check_output',side_effect=output),patch.object(installer.subprocess,'run',side_effect=run),patch.object(installer,'fetch',side_effect=[json.dumps(metadata).encode(),artifact]),patch.object(installer.time,'sleep'):
                installer.install()
            manifest=json.loads((installer.PREFIX/'manifest.json').read_text())
            self.assertEqual(set(manifest['packages']),{'claude','codex','agy','pi'})
            self.assertEqual(set(installs),{'claude','codex','pi'})
            for cli in manifest['packages']:
                self.assertEqual(manifest['packages'][cli]['binary_digest'],hashlib.sha256((installer.PREFIX/'bin'/cli).read_bytes()).hexdigest())

class NativeRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_keyring_starts_inside_the_owned_runtime_container(self):
        from cursus.containers import Containers
        from tests.unit.test_containers import policy,RuntimeFixture
        from tests.support import workspace
        from uuid import uuid4
        with workspace() as ws:
            settings,ceilings=policy(ws.root)
            settings.update(native_keyring=True,hide_project_customizations=True)
            (ws.worktrees/'.agents').mkdir()
            fixture=RuntimeFixture();execs=[]
            async def command(*argv):
                if argv[0]=='exec':
                    execs.append(argv);return 0,b''
                return await fixture(*argv)
            runtime=Containers(settings,ws.state,ceilings,command)
            attempt=str(uuid4())
            await runtime.reserve(attempt,'agy','agy')
            try:
                await runtime.prepare(attempt,ws.worktrees,True)
                identity=runtime.entries[attempt]['id']
                self.assertEqual(execs,[('exec',identity,'/usr/local/bin/cursus-start-keyring')])
                created=next(call for call in fixture.calls if call[0]=='create')
                self.assertIn('--env=DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/cursus-session-bus',created)
                self.assertTrue(any('/workspace/.agents:' in arg for arg in created))
                self.assertFalse(any('/run/user/' in arg for arg in created))
            finally:
                await runtime.cleanup(attempt)

class PairingIntegrationTests(unittest.TestCase):
    def test_controller_config_is_derived_from_worker_output_without_profile_path_prompt(self):
        import pwd
        import tomllib
        from tests.unit.test_install_entrypoint import helper
        native=module('deploy/native_setup.py','native_pairing_fixture')
        writer=helper().toml_text
        manifest={'packages':{cli:dict(binary_digest='a'*64,observed_version='fixture-1.0') for cli in native.CLIS}}
        ceilings=dict(worker=2,claude=1,codex=1,agy=1,verifier=1,repository=1)
        profile=native.profiles(manifest,'sha256:'+'b'*64,{cli:'fixture-model' for cli in native.CLIS},'fixture-go',ceilings)
        for cli in native.CLIS:profile[cli]['probe_evidence']=['fixture-check']
        profile['qualification']='native-checked'
        repo=dict(owner='fixture',name='repo',object_format='sha1',allowed_target_refs=['refs/heads/main'],
                  phase_check_ids=['unit'],checks=[dict(id='unit',argv=['/usr/bin/python3','-m','unittest'],cwd='.',timeout_seconds=30)])
        worker=dict(service={'runner_id':'d2a619e7-44d7-4097-a70a-c07997819260','origin':'https://fixture.example.ts.net'},
                    capacity=ceilings,repositories=[repo])
        code=native.pairing_code(dict(format=1,config=worker,profile=writer(profile),bearer_digest='c'*64))
        guide=helper().Guide(SimpleNamespace(source=str(ROOT),host='controller',non_interactive=True))
        guide.user=pwd.getpwuid(__import__('os').getuid()).pw_name
        guide._tailscale = dict(BackendState='Running', Self={'DNSName':'fixture.example.ts.net.'},
                                Peer={'worker':{'DNSName':'worker.example.ts.net.'}},
                                User={'1':{'LoginName':'operator@example.com'}})
        questions=[]
        def ask(question,default=None):
            questions.append(question)
            if question.startswith('Paste the pairing code'):return code
            if 'Which Tailscale account' in question:return '1'
            if 'older pairing code' in question:return '1'
            if 'off_host_destination' in question:return 'private-backup'
            self.fail('Unexpected setup question: '+question)
        guide.ask=ask
        with tempfile.TemporaryDirectory() as folder:
            guide.root=Path(folder)
            with patch.object(sys,'path',[str(ROOT/'deploy'),*sys.path]):path=guide.configure()
            config=tomllib.loads(path.read_text())
            self.assertEqual(config['capacity'],ceilings)
            self.assertEqual(config['repositories'],[repo])
            self.assertEqual(config['runner']['id'],worker['service']['runner_id'])
            self.assertEqual(config['service']['external_origin'],worker['service']['origin'])
            self.assertEqual(guide.pending_bearer_digest,'c'*64)
            self.assertFalse(any('Absolute path' in q for q in questions))
            self.assertEqual(config['runner']['tailnet_node'],'worker.example.ts.net')
            self.assertEqual(config['service']['operator_login'],'operator@example.com')
        worker['service']['tailnet_node']='worker.example.ts.net'
        code=native.pairing_code(dict(format=1,config=worker,profile=writer(profile),bearer_digest='c'*64))
        with tempfile.TemporaryDirectory() as folder:
            guide.root=Path(folder)
            with patch.object(sys,'path',[str(ROOT/'deploy'),*sys.path]):path=guide.configure()
            self.assertEqual(tomllib.loads(path.read_text())['runner']['tailnet_node'],'worker.example.ts.net')
        guide._tailscale['Self']['DNSName']='wrong.example.ts.net.'
        with tempfile.TemporaryDirectory() as folder:
            guide.root=Path(folder)
            with patch.object(sys,'path',[str(ROOT/'deploy'),*sys.path]):
                with self.assertRaisesRegex(RuntimeError,'different controller'):guide.configure()
            self.assertFalse((guide.root/'control.toml').exists())

class NativeChecksTests(unittest.TestCase):
    def test_completed_checks_generate_immutable_scoped_evidence_and_failure_does_not(self):
        from cursus.contracts import Problem
        native=module('deploy/native_setup.py','native_check_fixture')
        manifest={'packages':{cli:dict(binary_digest='a'*64,observed_version='fixture') for cli in native.CLIS}}
        ceilings=dict(worker=1,claude=1,codex=1,agy=1,verifier=1,repository=1)
        @contextmanager
        def session(*args,**kwargs):yield 'owned-fixture'
        def output(identity,argv,body,rpc=False):
            cli=Path(argv[0]).name
            text='{"cursus_native_login":"ok"}'
            frames={'claude':[{'type':'result','subtype':'success','result':text}],
                    'codex':[{'type':'item.completed','item':{'type':'agent_message','text':text}},{'type':'turn.completed'}],
                    'agy':[{'event':'result','result':{'status':'SUCCESS','response':text}}],
                    'pi':[{'type':'message_end','message':{'role':'assistant','content':[{'type':'text','text':text}]}},{'type':'agent_end'}]}
            return '\n'.join(json.dumps(f) for f in frames[cli]).encode()
        with tempfile.TemporaryDirectory() as folder:
            manager=native.NativeSetup.__new__(native.NativeSetup)
            manager.root=Path(folder);manager.session=session;manager.help_check=lambda *a:None
            manager.guide=SimpleNamespace(ask=lambda question:'5 EUR' if 'charge' in question else 'yes')
            credentials={cli:[{'id':cli+'-1','evidence':'pending'}] for cli in native.CLIS}
            profile=native.profiles(manifest,'sha256:'+'b'*64,{cli:'fixture-model' for cli in native.CLIS},'fixture-go',ceilings)
            with patch.object(native.time,'sleep'),patch.object(manager,'probe',side_effect=output) as probe:
                result=manager.check('fixture-image',credentials,profile)
                self.assertEqual(probe.call_count,9)
            self.assertEqual(result['qualification'],'native-checked')
            record=Path(result['evidence_record'])
            evidence=json.loads(record.read_text())
            self.assertEqual(len(evidence['records']),9)
            self.assertIn('full M3 acceptance remains pending',evidence['scope'])
            self.assertEqual(record.stat().st_mode & 0o777,0o600)
            failed=native.profiles(manifest,'sha256:'+'b'*64,{cli:'fixture-model' for cli in native.CLIS},'fixture-go',ceilings)
            with patch.object(native.time,'sleep'),patch.object(manager,'probe',return_value=b'{"type":"error"}'):
                with self.assertRaises(Problem):manager.check('fixture-image',credentials,failed)
            self.assertEqual(failed['qualification'],'unqualified')
            self.assertEqual(len(list(Path(folder).glob('checks-*.json'))),1)

class NativeSelectionTests(unittest.TestCase):
    def test_reader_exports_only_selected_fields_and_handles_missing_defaults(self):
        native=module('deploy/native_setup.py','native_selection_fixture')
        manager=object.__new__(native.NativeSetup)
        @contextmanager
        def session(*args,**kwargs):yield 'fixture-container'
        manager.session=session
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            fixtures={'.claude/settings.json':json.dumps(dict(model='chosen-claude',env={'PRIVATE_FIXTURE':'do-not-export'})),
                      '.codex/config.toml':'model = "chosen-codex"\nprivate_fixture = "do-not-export"\n',
                      '.gemini/antigravity-cli/settings.json':json.dumps(dict(model='Chosen AGY',private_fixture='do-not-export')),
                      '.pi/agent/settings.json':json.dumps(dict(defaultModel='chosen-pi',defaultProvider='chosen-provider',private_fixture='do-not-export'))}
            for name,content in fixtures.items():
                path=root/name;path.parent.mkdir(parents=True);path.write_text(content)
            def podman(*args,**kwargs):
                self.assertEqual(args[:4],('exec','fixture-container','/usr/bin/python3','-c'))
                script=args[4].replace("Path('/home/session')",'Path('+repr(folder)+')')
                result=subprocess.run([sys.executable,'-c',script,args[5]],text=True,capture_output=True,check=True,timeout=5)
                self.assertNotIn('do-not-export',result.stdout+result.stderr)
                return result
            manager.podman=podman
            for cli,model in [('claude','chosen-claude'),('codex','chosen-codex'),('agy','Chosen AGY'),('pi','chosen-pi')]:
                selected=manager.selection('image',cli,{})
                self.assertEqual(selected['model'],model)
                self.assertEqual(set(selected),{'model','provider'} if cli=='pi' else {'model'})
            (root/'.claude/settings.json').write_text('{}')
            self.assertEqual(manager.selection('image','claude',{}),{})
            (root/'.claude/settings.json').unlink()
            (root/'.claude/settings.json').symlink_to(root/'.pi/agent/settings.json')
            self.assertEqual(manager.selection('image','claude',{}),{})

    def test_saved_models_are_reused_without_input_or_inference(self):
        native=module('deploy/native_setup.py','native_selection_no_input')
        manager=object.__new__(native.NativeSetup)
        manager.selection=lambda image,cli,domain:dict(model='selected-'+cli,**({'provider':'selected-provider'} if cli=='pi' else {}))
        models,provider=manager.selections('image',{cli:[{}] for cli in native.CLIS})
        self.assertEqual(models,{cli:'selected-'+cli for cli in native.CLIS})
        self.assertEqual(provider,'selected-provider')
