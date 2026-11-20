"""Durable reusable UIDs and explicit native-auth inputs, independent of roles."""
import os
from pathlib import Path
import pwd
import shutil
import stat
from cursus.contracts import Problem, validate, _path


class IdentityPool:
    def __init__(self, accounts, journal):
        self.accounts, self.journal = accounts, journal
        self.held = {}
        for record in journal.records:
            if record['kind'] == 'identity_lease':
                lease = record['value']
                if lease['index'] >= len(accounts) or accounts[lease['index']]['user'] != lease['user']:
                    raise Problem('invalid_config','A retained identity lease no longer matches the pool.')
                self.held[lease['attempt_id']] = lease['index']
            elif record['kind'] == 'identity_release':
                self.held.pop(record['value'],None)

    def acquire(self, attempt_id):
        if attempt_id in self.held:
            return self.accounts[self.held[attempt_id]]
        index = next((i for i in range(len(self.accounts)) if i not in self.held.values()),None)
        if index is None:
            raise Problem('capacity', 'All execution identities are held.')
        self.journal.record('identity_lease',dict(attempt_id=attempt_id,index=index,user=self.accounts[index]['user']))
        self.held[attempt_id] = index
        return self.accounts[index]

    def release(self, attempt_id):
        if attempt_id in self.held:
            self.journal.record('identity_release',attempt_id)
            self.held.pop(attempt_id)


def prepare_home(root, attempt_id, account, source, auth_files):
    """Copy only operator-declared native credential files, never whole homes.

    No file contents enter prompts, configuration snapshots or logs. Native login
    happens once per CLI source identity. Renewal is serialized on that source;
    an invocation's private copy is disposable and is never copied back.
    """
    validate('Id',attempt_id)
    root = Path(root)
    root.mkdir(mode=0o711,parents=True,exist_ok=True)
    target = root / attempt_id
    target.mkdir(mode=0o700)
    user = pwd.getpwnam(account['user'])
    os.chown(target,user.pw_uid,user.pw_gid)
    for name in auth_files:
        _path(name)
        relative = Path(name)
        current = Path(source['home'])
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise Problem('invalid_config', 'Native auth inputs cannot be symlinks.')
        info = current.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1048576:
            raise Problem('invalid_config','Native auth input must be a bounded regular file.')
        destination = target / relative
        destination.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        with current.open('rb') as incoming, destination.open('xb') as outgoing:
            os.fchmod(outgoing.fileno(),0o600)
            copied = 0
            while chunk := incoming.read(65536):
                copied += len(chunk)
                if copied > 1048576:
                    raise Problem('invalid_config','Native auth input grew beyond its bound.')
                outgoing.write(chunk)
            os.fchown(outgoing.fileno(),user.pw_uid,user.pw_gid)
        current = destination.parent
        while current != target:
            os.chown(current,user.pw_uid,user.pw_gid)
            current.chmod(0o700)
            current = current.parent
    return dict(account,home=str(target))


def remove_home(root, attempt_id):
    validate('Id',attempt_id)
    path = Path(root) / attempt_id
    if path.exists():
        if path.is_symlink() or not shutil.rmtree.avoids_symlink_attacks:
            raise Problem('storage','Refusing unsafe execution-home cleanup.')
        shutil.rmtree(path)
