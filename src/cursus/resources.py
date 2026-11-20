"""Hardware admission and systemd cgroup limits for direct native CLI children."""
import asyncio
import os
from pathlib import Path
from uuid import uuid4
from cursus.contracts import Problem


def validate_resources(value):
    fields = {'reserve_memory_bytes','reserve_disk_bytes','worker_memory_bytes',
              'frontier_memory_bytes','verifier_memory_bytes','cpu_percent','tasks_max','repository_bytes'}
    if not isinstance(value,dict) or set(value)!=fields:
        raise Problem('invalid_config','Missing or unsupported resource limits.')
    if any(type(n) is not int or n<=0 for n in value.values()):
        raise Problem('invalid_config','Resource limits must be positive integers.')
    physical = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
    if value['reserve_memory_bytes'] >= physical:
        raise Problem('invalid_config','Memory reserve consumes the whole host.')
    return dict(value)


class Resources:
    def __init__(self, settings, root):
        self.settings, self.root, self.held = settings, Path(root), {}
        self.total = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')

    def amount(self, job):
        category = 'worker' if job['slot']=='worker' else 'verifier' if job['slot']=='verifier' else 'frontier'
        return self.settings[category+'_memory_bytes'] if job['slot']!='repository' else 0

    def available(self, job):
        import shutil
        needed = self.amount(job)
        available = next((int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')),0)
        return (available >= needed+self.settings['reserve_memory_bytes']
                and sum(self.held.values()) + needed <= self.total-self.settings['reserve_memory_bytes']
                and shutil.disk_usage(self.root).free > self.settings['reserve_disk_bytes'])

    def reserve(self, attempt_id, job):
        if attempt_id not in self.held:
            if not self.available(job):
                raise Problem('capacity','Hardware reserve prevents admission.')
            self.held[attempt_id] = self.amount(job)

    def release(self, attempt_id):
        self.held.pop(attempt_id,None)

    def command(self, argv, workspace, user, environment, category):
        unit = 'cursus-task-' + uuid4().hex + '.service'
        memory = self.settings[category+'_memory_bytes']
        command = ['/usr/bin/systemd-run','--quiet','--wait','--pipe','--collect',
            '--service-type=exec','--unit='+unit,'--uid='+user.pw_name,
            '--gid='+str(user.pw_gid),'--working-directory='+str(workspace),
            '--slice=cursus-execution.slice','--property=MemoryMax='+str(memory), '--property=MemorySwapMax=0',
            '--property=CPUQuota='+str(self.settings['cpu_percent'])+'%',
            '--property=TasksMax='+str(self.settings['tasks_max']),
            '--property=KillMode=control-group','--property=TimeoutStopSec=5s','--property=NoNewPrivileges=yes',
            '--property=BindsTo=cursus-runner.service','--property=After=cursus-runner.service',
            '--property=PartOf=cursus-runner.service']
        for key,value in environment.items():
            command.append('--setenv='+key+'='+value)
        # systemd manager defaults must not leak into the native CLI. env -i
        # execs that CLI with only the explicit non-secret allowlist.
        clean = [key+'='+value for key,value in environment.items()]
        return unit, [*command,'--','/usr/bin/env','-i',*clean,*argv]

    async def stop(self, unit):
        # systemd-run is a transport process; its death alone cannot prove that
        # the native CLI and all descendants stopped. Query the actual unit.
        try:
            process = await asyncio.create_subprocess_exec('/usr/bin/systemctl','stop',unit,
                stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
        except OSError:
            raise Problem('unknown_stop','Execution cgroup supervisor is unavailable.') from None
        try:
            await asyncio.wait_for(process.wait(),10)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise Problem('unknown_stop','Execution cgroup stop was not confirmed.') from None
        try:
            check = await asyncio.create_subprocess_exec('/usr/bin/systemctl','show',unit,
                '--property=ActiveState','--value',stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
        except OSError:
            raise Problem('unknown_stop','Execution cgroup state is unavailable.') from None
        try:
            output,_ = await asyncio.wait_for(check.communicate(),5)
        except TimeoutError:
            check.kill()
            await check.wait()
            raise Problem('unknown_stop','Execution cgroup state query timed out.') from None
        if check.returncode!=0 or output.strip() not in (b'inactive',b'failed'):
            raise Problem('unknown_stop','Execution cgroup remains active.')
