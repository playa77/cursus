"""Immutable bounded files; metadata authorization belongs to Control (ADR 0007)."""

from hashlib import sha256
import os
from pathlib import Path
import shutil
import stat
import tempfile
from cursus.contracts import Problem, validate

MAX_FILE = 32 * 1024 * 1024
MAX_PHASE = 256 * 1024 * 1024


class Artifacts:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise Problem('storage', 'Artifact root must not be a symlink.')

    def path(self, attempt_id, file_id):
        validate('Id', attempt_id)
        validate('Id', file_id)
        # Flat, server-computed names avoid all caller-controlled path traversal.
        return self.root / f'{attempt_id}-{file_id}'

    async def stage(self, attempt_id, ref, stream):
        validate('FileRef', ref)
        if ref['length'] > MAX_FILE:
            raise Problem('payload_too_large', 'Artifact exceeds 32 MiB.')
        if shutil.disk_usage(self.root).free < ref['length'] + 1048576:
            raise Problem('storage', 'Artifact storage reserve exhausted.')
        target = self.path(attempt_id, ref['id'])
        fd, temporary = tempfile.mkstemp(prefix='.upload-', dir=self.root)
        digest, size = sha256(), 0
        try:
            with os.fdopen(fd, 'wb') as output:
                async for chunk in stream:
                    size += len(chunk)
                    if size > ref['length']:
                        raise Problem('artifact_conflict', 'Artifact length differs.')
                    digest.update(chunk)
                    output.write(chunk)
                if size != ref['length'] or digest.hexdigest() != ref['digest']:
                    raise Problem('artifact_conflict', 'Artifact digest or length differs.')
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                # An interrupted metadata commit may leave exactly these bytes.
                with self.open(attempt_id, ref):
                    pass
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return ref
        finally:
            Path(temporary).unlink(missing_ok=True)

    def open(self, attempt_id, ref):
        validate('FileRef', ref)
        try:
            fd = os.open(self.path(attempt_id, ref['id']), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError:
            raise Problem('unavailable', 'Artifact bytes unavailable.') from None
        source = os.fdopen(fd, 'rb')
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size != ref['length']:
                raise Problem('artifact_conflict', 'Stored artifact differs.')
            digest = sha256()
            while chunk := source.read(65536):
                digest.update(chunk)
            if digest.hexdigest() != ref['digest']:
                raise Problem('artifact_conflict', 'Stored artifact differs.')
            source.seek(0)
            return source
        except BaseException:
            source.close()
            raise
