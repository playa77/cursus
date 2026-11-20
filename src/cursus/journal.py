"""Streaming hash-chain journal with disk-backed iteration, not a RAM mirror."""
import fcntl
from hashlib import sha256
import os
from pathlib import Path
import shutil
from uuid import uuid4
from cursus.contracts import Problem, canonical_json, decode_json

MAX_RECORD = 2 * 1024 * 1024
TERMINAL_RESERVE = 16 * MAX_RECORD


class Records:
    def __init__(self, path):
        self.path = path
        self.count = 0

    def __iter__(self):
        # Capture the committed prefix: callers may append while iterating.
        size = self.path.stat().st_size if self.path.exists() else 0
        with self.path.open('rb') as source:
            while source.tell() < size:
                yield decode_json(source.readline(MAX_RECORD + 1))['record']

    def __len__(self):
        return self.count


class Journal:
    def __init__(self, root, max_bytes=2147483648):
        self.max_bytes = max_bytes
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lock = (self.root / 'lock').open('a+b')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise
        self.path = self.root / 'journal.jsonl'
        self.path.touch(mode=0o600, exist_ok=True)
        self.records, self.digest = Records(self.path), '0' * 64
        self.generation = None
        try:
            with self.path.open('r+b') as source:
                offset = 0
                while line := source.readline(MAX_RECORD + 1):
                    if len(line) > MAX_RECORD:
                        raise Problem('journal_corrupt', 'Journal record exceeds its bound.')
                    if not line.endswith(b'\n'):
                        source.truncate(offset)
                        source.flush()
                        os.fsync(source.fileno())
                        break
                    item = decode_json(line)
                    expected = sha256(self.digest.encode() + canonical_json(item['record'])).hexdigest()
                    if item['digest'] != expected:
                        raise Problem('journal_corrupt', 'Journal integrity is uncertain.')
                    self.digest = expected
                    self.records.count += 1
                    if item['record']['kind'] == 'generation':
                        self.generation = item['record']['value']
                    offset += len(line)
            self.stream = self.path.open('ab', buffering=0)
            os.chmod(self.path, 0o600)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            if self.generation is None:
                self.generation = str(uuid4())
                self.record('generation', self.generation)
        except BaseException:
            self.close()
            raise

    def record(self, kind, value):
        record = {'kind': kind, 'value': value}
        digest = sha256(self.digest.encode() + canonical_json(record)).hexdigest()
        raw = canonical_json({'record': record, 'digest': digest}) + b'\n'
        terminal = kind in ('ack','retire','directive','identity_release') or (kind == 'event' and value.get('kind') == 'final')
        reserve = 0 if terminal else TERMINAL_RESERVE
        if len(raw) > MAX_RECORD or self.path.stat().st_size + len(raw) + reserve > self.max_bytes or shutil.disk_usage(self.root).free < len(raw) + reserve:
            raise Problem('storage', 'Journal reserve exhausted; intake is stopped.')
        remaining = memoryview(raw)
        while remaining:
            written = self.stream.write(remaining)
            if not written:
                raise OSError('Journal write did not complete')
            remaining = remaining[written:]
        os.fsync(self.stream.fileno())
        self.digest = digest
        self.records.count += 1
        return len(self.records)

    def close(self):
        if hasattr(self, 'stream'):
            self.stream.close()
        self.lock.close()
