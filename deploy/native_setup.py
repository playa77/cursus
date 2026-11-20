"""Install native tools; authentication is a separate operator action.

All Podman commands use the stable rootless runner identity. No host credentials
or developer-agent environment are read or copied. ADR 0015 ends the installer
entry point after image/domain preparation; qualification helpers do not run.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import base64
import fcntl
import json
import os
from pathlib import Path
import pwd
import re
import selectors
import signal
import shutil
import subprocess
import time
from uuid import uuid4
import zlib

CLIS=('claude','codex','agy','pi')
AUTH={'claude':['.claude'], 'codex':['.codex'], 'agy':['.gemini','.local/share/keyrings'], 'pi':['.pi/agent']}
READ=['read','list','search']
WRITE=[*READ,'write','edit','bash']


def pairing_code(bundle):
    return base64.urlsafe_b64encode(zlib.compress(json.dumps(bundle).encode())).decode()


def read_pairing(code):
    if len(code)>65536:
        raise ValueError('Pairing code exceeds limit')
    data=zlib.decompressobj().decompress(base64.urlsafe_b64decode(code),1048577)
    if len(data)>1048576:
        raise ValueError('Pairing code exceeds expanded limit')
    bundle=json.loads(data)
    if bundle.get('format')!=1 or set(bundle)!={'format','config','profile','bearer_digest'}:
        raise ValueError('Unsupported worker pairing code')
    return bundle


def profiles(manifest,image,models,provider,ceilings):
    """Compile known native interfaces; installed help is checked before use."""
    common=dict(credential_concurrency=1,prompt_transport='stdin',tool_allowlist=READ,
                qualified_roles=[],probe_evidence=[],reasoning='medium')
    result=dict(schema_version=2,image=image,qualification='unqualified',evidence_record='installer native checks')
    roles={'claude':['interviewer','planner','advocate'], 'codex':['reviewer','critic'],
           'agy':['judge'], 'pi':['worker','debug']}
    for cli in CLIS:
        entry=manifest['packages'][cli]
        result[cli]=dict(common,binary='/usr/local/bin/'+cli,binary_digest=entry['binary_digest'],
                         version=entry['observed_version'],model=models[cli],qualified_roles=roles[cli],
                         credential_concurrency=ceilings['worker' if cli=='pi' else cli])
    result['claude'].update(fixed_argv=['-p','--output-format','stream-json','--verbose','--model',models['claude'],'--effort','medium'],
                            read_only_argv=['--tools','Read,Glob,Grep'],clean_config_argv=['--safe-mode'])
    result['codex'].update(fixed_argv=['exec','--json','--model',models['codex'],'-c','model_reasoning_effort="medium"'],
                           read_only_argv=['--sandbox','read-only'],clean_config_argv=['--ignore-user-config','--ephemeral'])
    settings={'permissions':{'deny':['command(*)','write_file(*)','mcp(*)','web(*)']}}
    result['agy'].update(fixed_argv=['-p','--output-format','stream-json','--model',models['agy'],'--effort','medium'],
                         read_only_argv=['--mode','plan'],clean_config_argv=['--disable-slash-commands','--settings',json.dumps(settings)])
    clean=['--no-extensions','--no-skills','--no-prompt-templates','--no-themes']
    result['pi'].update(provider=provider,tool_allowlist=WRITE,prompt_transport='rpc',
                        fixed_argv=['--mode','rpc','--provider',provider,'--model',models['pi'],'--thinking','medium',
                                    '--tools','read,ls,find,grep,write,edit,bash'],clean_config_argv=clean,
                        role_profiles={'scout':dict(qualified_roles=['scout'],tool_allowlist=READ,prompt_transport='argument',
                            fixed_argv=['--mode','json','--print','--provider',provider,'--model',models['pi'],'--thinking','medium'],
                            read_only_argv=['--tools','read,ls,find,grep'])})
    return result


class NativeSetup:
    def __init__(self,guide,config):
        self.guide,self.config=guide,config
        self.account=pwd.getpwnam('cursus-runner')
        self.root=Path('/var/lib/cursus-runner/native-setup')
        if self.root.is_symlink() or (self.root.exists() and self.root.stat().st_uid!=self.account.pw_uid):
            raise RuntimeError('Refusing conflicting native onboarding directory')
        self.root.mkdir(mode=0o700,exist_ok=True)
        os.chown(self.root,self.account.pw_uid,self.account.pw_gid)
        uid=str(self.account.pw_uid)
        self.prefix=['runuser','-u','cursus-runner','--','env','-i','HOME=/var/lib/cursus-runner',
                     'PATH=/usr/bin:/bin','LANG=C.UTF-8','XDG_RUNTIME_DIR=/run/user/'+uid,
                     'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/'+uid+'/bus',
                     '/usr/bin/podman','--remote=false','--cgroup-manager=systemd']
        self.ledger=self.root/'container.json'
        self.lock_fd=os.open(self.root/'setup.lock',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(self.lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.recover()
        except BaseException:
            os.close(self.lock_fd)
            raise

    def save(self, state):
        fd=os.open(self.ledger,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as output:
            json.dump(state,output);output.flush();os.fsync(output.fileno())
        fd=os.open(self.root,os.O_DIRECTORY|os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)

    def podman(self,*args,**kwargs):
        kwargs.setdefault('timeout',30)
        # Rootless Podman re-enters cwd after dropping privileges; the caller’s
        # private home may be inaccessible to cursus-runner.
        kwargs.setdefault('cwd',self.root)
        return subprocess.run([*self.prefix,*map(str,args)],check=True,**kwargs)

    def own_dir(self,path):
        if path.is_symlink():raise RuntimeError('Refusing native setup symlink: '+str(path))
        if path.exists() and path.stat().st_uid!=self.account.pw_uid:
            raise RuntimeError('Refusing conflicting native setup owner: '+str(path))
        path.mkdir(mode=0o700,parents=True,exist_ok=True)
        os.chown(path,self.account.pw_uid,self.account.pw_gid)
        path.chmod(0o700)

    def build(self):
        context=self.guide.source/'deploy/native'
        sources=[context/name for name in ('Containerfile','install-tools.py','start-keyring.sh')]
        if context.is_symlink() or any(p.is_symlink() or not p.is_file() for p in sources):
            raise RuntimeError('Native build context must contain regular in-tree files')
        recipe=sha256(b''.join(p.name.encode()+b'\0'+p.read_bytes() for p in sources)).hexdigest()
        image_file=self.root/(recipe+'-image-id')
        if image_file.exists():
            image=image_file.read_text().strip()
            self.podman('image','exists',image)
            return image
        build=self.root/'build'
        self.own_dir(build)
        for source in sources:
            if source.is_symlink() or not source.is_file():
                raise RuntimeError('Native build context must contain regular source files')
            destination=build/source.name
            shutil.copyfile(source,destination)
            os.chown(destination,self.account.pw_uid,self.account.pw_gid)
        print('Installing Claude Code, Codex CLI, Antigravity and pi in the runtime image. This may take several minutes.',flush=True)
        self.podman('build','--pull=missing','--tag','localhost/cursus-native:'+str(uuid4()),'--iidfile',build/'image-id',build,timeout=1800)
        image=(build/'image-id').read_text().strip()
        if not re.fullmatch('sha256:[0-9a-f]{64}',image):raise RuntimeError('Invalid built image ID')
        image_file.write_text(image+'\n')
        return image

    def domains(self):
        credentials={}
        for cli in CLIS:
            count=self.config['capacity']['worker' if cli=='pi' else cli]
            credentials[cli]=[]
            for index in range(count):
                ident=f'{cli}-{index+1}'
                mounts=[]
                for number,target in enumerate(AUTH[cli]):
                    source=Path('/var/lib/cursus-runner/auth')/ident/str(number)
                    self.own_dir(source.parent);self.own_dir(source)
                    mounts.append(dict(source=str(source),target='/home/session/'+target))
                credentials[cli].append(dict(id=ident,evidence='installer-created domain; manual login pending: '+str(self.root),mounts=mounts))
        return credentials

    def recover(self):
        if not self.ledger.exists():return
        state=json.loads(self.ledger.read_text())
        exists=subprocess.run([*self.prefix,'container','exists',state['name']],capture_output=True,timeout=20,cwd=self.root)
        if exists.returncode==1:
            self.ledger.unlink();return
        if exists.returncode:raise RuntimeError('Cannot inspect prior native onboarding container; reservation retained')
        value,=json.loads(self.podman('inspect',state['name'],capture_output=True,text=True).stdout)
        if value['Config']['Labels'].get('io.cursus.onboarding')!=state['token'] or (state.get('id') and value['Id']!=state['id']):
            raise RuntimeError('Onboarding container identity mismatch; refusing cleanup')
        if value['State']['Running']:self.podman('stop','--time=10',value['Id'])
        self.podman('rm',value['Id'])
        self.ledger.unlink()

    @contextmanager
    def session(self,image,domain=None,readonly=False):
        self.recover()
        state=dict(name='cursus-login-'+str(uuid4()),token=uuid4().hex,id=None)
        self.save(state)
        workspace=self.root/'workspace';self.own_dir(workspace)
        resource=self.config['containers']['resources']['agent']
        argv=['create','--pull=never','--name',state['name'],'--label','io.cursus.onboarding='+state['token'],
              '--entrypoint=/usr/bin/sleep','--image-volume=ignore','--unsetenv-all','--userns=keep-id:uid=1000,gid=1000','--user=1000:1000',
              '--cap-drop=ALL','--security-opt=no-new-privileges','--pid=private','--ipc=private','--read-only','--network=private',
              '--memory='+str(resource['memory_mb'])+'m','--memory-swap='+str(resource['memory_mb'])+'m',
              '--cpus='+str(resource['cpu_millis']/1000),'--pids-limit='+str(resource['pids']),
              '--tmpfs=/tmp:rw,nosuid,nodev,size='+str(resource['tmp_mb'])+'m',
              '--tmpfs=/home/session:rw,nosuid,nodev,uid=1000,gid=1000,mode=700,size='+str(resource['home_mb'])+'m',
              '--env=HOME=/home/session','--env=PATH=/usr/local/bin:/usr/bin:/bin','--env=LANG=C.UTF-8',
              '--env=SSH_TTY=/dev/tty','--env=SSH_CONNECTION=127.0.0.1 0 127.0.0.1 22','--workdir=/workspace','--log-driver=none','--restart=no',
              '--volume',str(workspace)+':/workspace:'+('ro' if readonly else 'rw')]
        if domain and domain['id'].startswith('agy-'):
            argv += ['--env=DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/cursus-session-bus',
                     '--env=XDG_RUNTIME_DIR=/tmp/cursus-runtime']
        for mount in (domain or {}).get('mounts',[]):argv+=['--volume',mount['source']+':'+mount['target']+':rw']
        try:
            identity=self.podman(*argv,image,'infinity',capture_output=True,text=True).stdout.strip()
            if not re.fullmatch('[0-9a-f]{64}',identity):raise RuntimeError('Invalid onboarding container ID')
            state['id']=identity;self.save(state)
            self.podman('start',identity,capture_output=True)
            if domain and domain['id'].startswith('agy-'):
                self.podman('exec',identity,'/usr/local/bin/cursus-start-keyring',input=b'',capture_output=True)
            yield identity
        finally:
            self.recover()

    def login(self,image,credentials):
        instructions={'claude':'Sign in to Claude Code with your subscription; exit when login completes.',
                      'codex':'Sign in with ChatGPT using the displayed device flow.',
                      'agy':'Open the displayed URL on your PC and enter the returned authorization code. Exit when signed in.',
                      'pi':'Type /login, choose the agreed OpenCode Go provider, complete native enrollment, then exit.'}
        for cli in CLIS:
            for domain in credentials[cli]:
                self.guide.tty.write('\nLOGIN REQUIRED — '+cli+' ('+domain['id']+'). '+instructions[cli]+'\n')
                self.guide.tty.flush()
                self.guide.ask('Press Enter after reading; type login to open the installed '+cli,'login')
                with self.session(image,domain) as identity:
                    args={'claude':['claude','auth','login'],'codex':['codex','login','--device-auth'],
                          'agy':['agy'],'pi':['pi']}[cli]
                    self.podman('exec','--interactive','--tty',identity,*args,
                                stdin=self.guide.tty.reader,stdout=self.guide.tty.writer,stderr=self.guide.tty.writer,timeout=900)

    def selection(self, image, cli, domain):
        """Export only model/provider fields from this install's own settings.

        Settings locations/keys: Claude settings/model-config docs, Codex config
        basics, Antigravity settings, and pi configuration/settings references.
        Never return whole settings, auth files, or developer-agent state.
        """
        script = r"""
import json, os, sys, tomllib
from pathlib import Path
cli = sys.argv[1]
paths = {'claude':'.claude/settings.json', 'codex':'.codex/config.toml',
         'agy':'.gemini/antigravity-cli/settings.json', 'pi':'.pi/agent/settings.json'}
try:
    path = Path('/home/session') / paths[cli]
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as source:
        raw = source.read(1048577)
    if len(raw) > 1048576:
        raise ValueError()
    data = tomllib.loads(raw.decode()) if cli == 'codex' else json.loads(raw)
    result = {'model':data.get('defaultModel' if cli == 'pi' else 'model')}
    if cli == 'pi': result['provider'] = data.get('defaultProvider')
    if any(not isinstance(v,str) or not v.strip() or len(v)>256 or any(ord(c)<32 for c in v) for v in result.values()):
        raise ValueError()
except (OSError, ValueError, TypeError, AttributeError):
    result = {}
print(json.dumps(result))
"""
        with self.session(image,domain,readonly=True) as identity:
            result = self.podman('exec',identity,'/usr/bin/python3','-c',script,cli,
                                 capture_output=True,text=True,timeout=15)
        return json.loads(result.stdout)

    def selections(self, image, credentials):
        models = {}
        provider = None
        for cli in CLIS:
            domain = credentials[cli][0]
            selected = self.selection(image,cli,domain)
            if not selected:
                self.guide.tty.write('\nChoose the model for '+cli+' in its own model selector and save it as the default.\nFor pi also choose the provider. Exit the app after saving. Do not send a task or prompt.\n')
                self.guide.tty.flush()
                self.guide.ask('Press Enter to open '+cli+' for this choice.','open')
                with self.session(image,domain) as identity:
                    self.podman('exec','--interactive','--tty',identity,cli,
                                stdin=self.guide.tty.reader,stdout=self.guide.tty.writer,stderr=self.guide.tty.writer,timeout=1800)
                selected = self.selection(image,cli,domain)
            if not selected:
                raise RuntimeError(cli+' did not save a readable model selection. Save a default using its native model selector, then rerun. No model ID transcription is required.')
            models[cli] = selected['model']
            if cli == 'pi': provider = selected['provider']
        return models,provider

    def probe(self, identity, argv, body, rpc=False):
        # Keep RPC stdin open until agent_end. communicate(input=...) closes it
        # immediately and can abort pi before its terminal event.
        command=[*self.prefix,'exec','--interactive',identity,'/usr/bin/timeout',
                 '--signal=TERM','--kill-after=10s','120s',*argv]
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,start_new_session=True,cwd=self.root,
                                 env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8'})
        selector=selectors.DefaultSelector()
        output=bytearray(); diagnostics=bytearray(); pending=bytearray()
        try:
            process.stdin.write(body);process.stdin.flush()
            if not rpc:process.stdin.close()
            selector.register(process.stdout,selectors.EVENT_READ,'stdout')
            selector.register(process.stderr,selectors.EVENT_READ,'stderr')
            deadline=time.monotonic()+140
            while selector.get_map():
                if time.monotonic()>=deadline:raise RuntimeError('Native check time budget exhausted')
                for key,_ in selector.select(timeout=1):
                    data=os.read(key.fileobj.fileno(),65536)
                    if not data:
                        selector.unregister(key.fileobj);continue
                    target=output if key.data=='stdout' else diagnostics
                    target.extend(data)
                    if len(target)>1048576:raise RuntimeError('Native check output exceeds bound')
                    if rpc and key.data=='stdout':
                        pending.extend(data)
                        while b'\n' in pending:
                            line,_,rest=pending.partition(b'\n');pending=bytearray(rest)
                            if line.strip() and json.loads(line).get('type')=='agent_end' and not process.stdin.closed:
                                process.stdin.close()
            if process.wait(timeout=5):raise RuntimeError('Native check failed; login state retained, no automatic retry')
            return bytes(output)
        finally:
            selector.close()
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGKILL);process.wait()
            for pipe in (process.stdin,process.stdout,process.stderr):
                if not pipe.closed:pipe.close()

    def check(self,image,credentials,profile):
        from cursus.execution import Execution
        amount=self.guide.ask('Maximum authorized charge for native checks (your currency; provider-side cap is not enforced)')
        calls=sum(len(v) for v in credentials.values())*2+1
        answer=self.guide.ask(f'Authorize up to {calls} native CLI invocations, one at a time, 120s each, no installer retries; native internal retries/cost are provider-controlled. Budget: {amount}. Type yes to run checks')
        if answer!='yes':raise RuntimeError('Checks postponed; installed native logins retained. Re-run to continue.')
        normalizer=Execution({}, object())
        record_path=self.root/('checks-'+str(uuid4())+'.json')
        records=[]
        for cli in CLIS:
            effective=profile[cli]
            for domain in credentials[cli]:
                for restart in range(2):
                    with self.session(image,domain,readonly=True) as identity:
                        self.help_check(identity,cli,effective)
                        argv=[effective['binary'],*effective['fixed_argv'],*effective.get('read_only_argv',[]),*effective['clean_config_argv']]
                        prompt='Reply with exactly this JSON, without markdown: {"cursus_native_login":"ok"}. Do not use tools.'
                        if effective['prompt_transport']=='rpc':
                            body=json.dumps(dict(id='cursus-turn-1',type='prompt',message=prompt))+'\n'
                        else:body=prompt
                        # A supervisor inside the container ends the native process
                        # group on timeout; removal below stops any descendants.
                        output=self.probe(identity,argv,body.encode(),effective['prompt_transport']=='rpc')
                        result=normalizer.normalize(cli,output)
                        if result!={'cursus_native_login':'ok'}:raise RuntimeError(cli+' native check returned an unexpected result')
                        records.append(dict(cli=cli,domain=domain['id'],restart=restart,utc=datetime.now(timezone.utc).isoformat(),
                                            stdout_digest=sha256(output).hexdigest()))
                    time.sleep(1)
            effective['probe_evidence']=[str(record_path)+'#'+cli]
        # pi scout has a different JSON/readonly transport; check that as well.
        effective={**profile['pi'],**profile['pi']['role_profiles']['scout']}
        with self.session(image,credentials['pi'][0],readonly=True) as identity:
            self.help_check(identity,'pi',effective)
            argv=[effective['binary'],*effective['fixed_argv'],*effective['read_only_argv'],*effective['clean_config_argv'],prompt]
            output=self.probe(identity,argv,b'')
            if normalizer.normalize('pi',output)!={'cursus_native_login':'ok'}:raise RuntimeError('pi scout check failed')
        records.append(dict(cli='pi',role='scout',domain=credentials['pi'][0]['id'],
                            utc=datetime.now(timezone.utc).isoformat(),stdout_digest=sha256(output).hexdigest()))
        with record_path.open('x') as record:
            record.write(json.dumps(dict(scope='native login, restart persistence and CLI protocol; full M3 acceptance remains pending',records=records),indent=2)+'\n')
            record.flush();os.fsync(record.fileno())
        record_path.chmod(0o600)
        for cli,domains in credentials.items():
            for domain in domains:
                domain['evidence']=str(record_path)+'#'+cli+'/'+domain['id']
        profile['qualification']='native-checked'
        profile['evidence_record']=str(record_path)
        return profile

    def help_check(self,identity,cli,profile):
        command=[cli,'exec','--help'] if cli=='codex' else [cli,'--help']
        help_run=self.podman('exec',identity,*command,capture_output=True,text=True,timeout=30)
        help_text=help_run.stdout+help_run.stderr
        for token in [*profile['fixed_argv'],*profile.get('read_only_argv',[]),*profile['clean_config_argv']]:
            if token.startswith('--') and token not in help_text:
                raise RuntimeError(cli+' installed version does not support required option '+token)

    def run(self):
        try:return self._run()
        finally:os.close(self.lock_fd)

    def _run(self):
        active=subprocess.run(['runuser','-u','cursus-runner','--','env',
                               'XDG_RUNTIME_DIR=/run/user/'+str(self.account.pw_uid),
                               'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/'+str(self.account.pw_uid)+'/bus',
                               'systemctl','--user','is-active','--quiet','cursus-runner'],timeout=20,capture_output=True,cwd=self.root)
        if active.returncode==0:raise RuntimeError('Drain and stop the active runner before changing native login domains.')
        if active.returncode not in (3,4):raise RuntimeError('Cannot establish runner inactivity; fix its user manager before native setup.')
        lifecycle=Path(self.config['service']['state_root'])/'execution/containers.json'
        if lifecycle.exists() and json.loads(lifecycle.read_text()):
            raise RuntimeError('Prior execution cleanup is unresolved; native login domains remain leased.')
        from cursus.config import capacity,container_settings
        capacity(self.config['capacity'])
        if shutil.disk_usage(self.root).free < self.config['containers']['disk_reserve_mb']*1024*1024:
            raise RuntimeError('Configured disk reserve is already exhausted; native image build refused.')
        image=self.build()
        credentials=self.domains()
        self.config['containers'].update(image=image,credentials=credentials)
        container_settings(self.config['containers'],self.config['capacity'],self.config['service'],self.config['publisher'])
        # ADR 0015: installation ends here. Authentication, model selection and
        # authenticated checks belong to the operator, not the installer.
        return None
