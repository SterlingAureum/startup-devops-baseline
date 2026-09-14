"""Linux private fsync/O_EXCL/flock write-ahead journal for reviewed adapters.

Per-directory/per-operation at-most-once recording is not authorization. Adapters
must pin one journal directory to the reviewed session and enforce clocks/scope.
Failures never delete, truncate, reset or repair existing evidence.
"""
from __future__ import annotations
import fcntl
import hashlib
import os
from pathlib import Path
import re
import stat
from guarded_runtime_rules import RuleViolation, require, parse_utc, json_object
import json


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encode(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':'))+'\n').encode()


def _binding(binding: dict) -> None:
    keys = {'environment','phase','main','inputs_sha256','state_sha256','proof_sha256','scope_sha256'}
    require(isinstance(binding, dict) and set(binding) == keys, 'journal-binding-schema')
    require(binding['environment'] in ('aws-dev','aws-test','aws-prod'), 'journal-environment')
    require(isinstance(binding['phase'], str) and re.fullmatch('[a-z][a-z0-9-]{0,63}', binding['phase']), 'journal-phase')
    for key in keys-{'environment','phase'}:
        size = 40 if key == 'main' else 64
        require(isinstance(binding[key], str) and re.fullmatch('[0-9a-f]{'+str(size)+'}', binding[key]), 'journal-binding-digest')


class AttemptJournal:
    """Append barriers/outcomes; caller invokes transport only after before returns.

    Intent with no outcome is uncertain and blocks all subsequent intents. A
    failure is terminal. Reopening requires a pinned marker hash and never erases
    consumption. The returned marker/events hashes are for private review evidence.
    """
    def __init__(self):
        raise RuleViolation('journal-use-reserve-or-open')

    @classmethod
    def _directory(cls, directory: Path, repository_root: Path):
        path, repo = Path(directory), Path(repository_root).resolve()
        require(path.is_absolute() and repo.is_dir(), 'journal-absolute-directory')
        for ancestor in (path, *path.parents):
            require(not ancestor.is_symlink(), 'journal-symlink-path')
        resolved = path.resolve()
        require(not resolved.is_relative_to(repo) and not any(resolved.is_relative_to(Path(x))
                for x in ('/tmp','/var/tmp','/dev','/proc','/sys')), 'journal-durable-outside-repository')
        fd = os.open(path, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            require(stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == os.getuid(), 'journal-directory-mode-or-owner')
            return fd
        except BaseException:
            os.close(fd)
            raise

    @classmethod
    def reserve(cls, directory: Path, binding: dict, timestamp: str, *, repository_root: Path):
        _binding(binding); parse_utc(timestamp)
        directory_fd = marker_fd = events_fd = None
        try:
            directory_fd = cls._directory(directory, repository_root)
            # An orphan log is evidence too; never pair it with a new marker.
            for name in ('events.jsonl','head.json','head-next.json'):
                try:
                    os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise RuleViolation('journal-existing-events-or-head')
            marker_fd = os.open('attempt.json', os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,
                                0o600, dir_fd=directory_fd)
            raw = encode({'schema':'guarded-attempt-v1','binding':binding,'reserved_at':timestamp})
            cls._write(marker_fd, raw); os.fsync(marker_fd); os.fsync(directory_fd)
            events_fd = os.open('events.jsonl', os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,
                                0o600, dir_fd=directory_fd)
            os.fsync(events_fd); os.fsync(directory_fd)
            marker_sha = digest(raw)
            head_fd = os.open('head.json', os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,
                              0o600, dir_fd=directory_fd)
            try:
                cls._write(head_fd, encode({'sequence':0,'last_event_sha256':marker_sha,
                                            'events_sha256':digest(b''),'events_bytes':0}))
                os.fsync(head_fd); os.fsync(directory_fd)
            finally:
                os.close(head_fd)
        except FileExistsError:
            raise RuleViolation('journal-attempt-already-consumed') from None
        except OSError:
            raise RuleViolation('journal-io-stop-preserve-evidence') from None
        finally:
            for fd in (events_fd, marker_fd, directory_fd):
                if fd is not None: os.close(fd)
        return cls.open(directory, binding, marker_sha, repository_root=repository_root)

    @staticmethod
    def _write(fd: int, raw: bytes) -> None:
        offset = 0
        while offset < len(raw):
            written = os.write(fd, raw[offset:])
            require(written > 0, 'journal-short-write')
            offset += written

    @classmethod
    def open(cls, directory: Path, binding: dict, expected_marker_sha256: str, *, repository_root: Path):
        _binding(binding)
        require(isinstance(expected_marker_sha256, str) and re.fullmatch('[0-9a-f]{64}', expected_marker_sha256), 'journal-marker-hash')
        obj = object.__new__(cls)
        obj.directory_fd = obj.marker_fd = None; obj.poisoned = False
        obj.binding = dict(binding); obj.marker_sha256 = expected_marker_sha256
        try:
            obj.directory_fd = cls._directory(directory, repository_root)
            obj.marker_fd = obj._file('attempt.json', os.O_RDONLY)
            obj.snapshot()
            return obj
        except BaseException as error:
            obj.close()
            if isinstance(error, OSError):
                raise RuleViolation('journal-io-stop-preserve-evidence') from None
            raise

    def _file(self, name: str, flags: int) -> int:
        fd = os.open(name, flags|os.O_NOFOLLOW|os.O_CLOEXEC, dir_fd=self.directory_fd)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
                    and info.st_uid == os.getuid() and info.st_nlink == 1, 'journal-file-mode-owner-or-link')
            return fd
        except BaseException:
            os.close(fd); raise

    @staticmethod
    def _read(fd: int) -> bytes:
        os.lseek(fd, 0, os.SEEK_SET); raw = bytearray()
        while True:
            chunk = os.read(fd, 65536)
            if not chunk: return bytes(raw)
            raw.extend(chunk)
            require(len(raw) <= 16*1024*1024, 'journal-size-limit')

    def _check_marker(self):
        require(self.directory_fd is not None and self.marker_fd is not None and not self.poisoned, 'journal-closed-or-uncertain')
        try:
            os.stat('head-next.json', dir_fd=self.directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise RuleViolation('journal-incomplete-head-commit')
        disk = os.stat('attempt.json', dir_fd=self.directory_fd, follow_symlinks=False)
        opened = os.fstat(self.marker_fd)
        require((disk.st_dev,disk.st_ino) == (opened.st_dev,opened.st_ino)
                and opened.st_nlink == 1 and stat.S_IMODE(opened.st_mode) == 0o600, 'journal-marker-replaced')
        raw = self._read(self.marker_fd)
        require(digest(raw) == self.marker_sha256, 'journal-marker-drift')
        marker = json_object(raw)
        require(set(marker) == {'schema','binding','reserved_at'} and marker['schema'] == 'guarded-attempt-v1'
                and marker['binding'] == self.binding, 'journal-marker-binding')
        return parse_utc(marker['reserved_at'])

    def _state(self, raw: bytes, reserved):
        require(not raw or raw.endswith(b'\n'), 'journal-incomplete-tail')
        previous = self.marker_sha256; pending = None; failed = complete = False
        operations = {}; last_time = reserved; sequence = 0
        for line in raw.splitlines(keepends=True):
            event = json_object(line)
            require(encode(event) == line and set(event) == {'sequence','kind','operation','at','previous_sha256'}, 'journal-event-schema')
            require(type(event['sequence']) is int and event['sequence'] == sequence+1
                    and event['previous_sha256'] == previous and not complete and not failed, 'journal-chain-or-terminal')
            at = parse_utc(event['at']); require(at >= last_time, 'journal-time-regression')
            operation, kind = event['operation'], event['kind']
            require(isinstance(operation, str) and re.fullmatch('[a-z][a-z0-9-]{0,63}', operation), 'journal-operation-tag')
            if kind == 'intent':
                require(pending is None and operation not in operations, 'journal-repeat-or-pending')
                operations[operation] = 'pending'; pending = operation
            elif kind in ('success','failure'):
                require(pending == operation, 'journal-outcome-without-intent')
                operations[operation] = kind; pending = None; failed = kind == 'failure'
            elif kind == 'observed-absent':
                require(pending is None and operation not in operations, 'journal-absence-after-attempt')
                operations[operation] = 'observed-absent'
            elif kind == 'phase-complete':
                require(operation == 'phase' and pending is None, 'journal-incomplete-phase')
                complete = True
            else:
                raise RuleViolation('journal-unknown-event')
            sequence += 1; previous = digest(line); last_time = at
        return {'operations':operations,'pending':pending,'failed':failed,'complete':complete,
                'sequence':sequence,'last_event_sha256':previous,'events_sha256':digest(raw),
                'last_time':last_time}

    @staticmethod
    def _head_value(state: dict, raw: bytes) -> dict:
        return {k:state[k] for k in ('sequence','last_event_sha256','events_sha256')} | {'events_bytes':len(raw)}

    def _check_head(self, state: dict, raw: bytes):
        fd = self._file('head.json', os.O_RDONLY)
        try:
            head = json_object(self._read(fd))
            require(type(head.get('sequence')) is int and type(head.get('events_bytes')) is int
                    and head == self._head_value(state, raw), 'journal-head-or-length-drift')
        finally:
            os.close(fd)

    def _commit_head(self, state: dict, raw: bytes):
        fd = os.open('head-next.json', os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,
                     0o600, dir_fd=self.directory_fd)
        try:
            self._write(fd, encode(self._head_value(state, raw))); os.fsync(fd)
        finally:
            os.close(fd)
        os.rename('head-next.json','head.json',src_dir_fd=self.directory_fd,dst_dir_fd=self.directory_fd)
        os.fsync(self.directory_fd)

    def snapshot(self) -> dict:
        require(self.marker_fd is not None, 'journal-closed-or-uncertain')
        fd = None
        try:
            fcntl.flock(self.marker_fd, fcntl.LOCK_EX)
            reserved = self._check_marker(); fd = self._file('events.jsonl', os.O_RDONLY)
            raw = self._read(fd); state = self._state(raw, reserved); self._check_head(state, raw)
            return {k:v for k,v in state.items() if k != 'last_time'}
        except OSError:
            self.poisoned = True
            raise RuleViolation('journal-io-stop-preserve-evidence') from None
        finally:
            if fd is not None: os.close(fd)
            fcntl.flock(self.marker_fd, fcntl.LOCK_UN)

    def _append(self, kind: str, operation: str, timestamp: str, expected_operations=None) -> str:
        parse_utc(timestamp)
        require(isinstance(operation, str) and re.fullmatch('[a-z][a-z0-9-]{0,63}', operation), 'journal-operation-tag')
        require(self.marker_fd is not None, 'journal-closed-or-uncertain')
        fd = None
        try:
            fcntl.flock(self.marker_fd, fcntl.LOCK_EX)
            reserved = self._check_marker(); fd = self._file('events.jsonl', os.O_RDWR|os.O_APPEND)
            raw = self._read(fd); state = self._state(raw, reserved); self._check_head(state, raw)
            if kind == 'phase-complete':
                require(isinstance(expected_operations, tuple) and all(isinstance(x, str) for x in expected_operations)
                        and len(expected_operations) == len(set(expected_operations))
                        and set(expected_operations) == set(state['operations']), 'journal-phase-scope')
            event = encode({'sequence':state['sequence']+1,'kind':kind,'operation':operation,
                            'at':timestamp,'previous_sha256':state['last_event_sha256']})
            updated = self._state(raw+event, reserved)  # Validate transition before any append.
            opened = os.fstat(fd); disk = os.stat('events.jsonl', dir_fd=self.directory_fd, follow_symlinks=False)
            require((opened.st_dev,opened.st_ino) == (disk.st_dev,disk.st_ino) and opened.st_nlink == 1,
                    'journal-events-replaced')
            self._write(fd, event); os.fsync(fd); os.fsync(self.directory_fd)
            self._commit_head(updated, raw+event)
            return digest(event)
        except OSError:
            self.poisoned = True
            raise RuleViolation('journal-io-stop-preserve-evidence') from None
        finally:
            if fd is not None: os.close(fd)
            fcntl.flock(self.marker_fd, fcntl.LOCK_UN)

    def before(self, operation: str, timestamp: str) -> str:
        return self._append('intent', operation, timestamp)

    def success(self, operation: str, timestamp: str) -> str:
        return self._append('success', operation, timestamp)

    def failure(self, operation: str, timestamp: str) -> str:
        return self._append('failure', operation, timestamp)

    def observed_absent(self, operation: str, timestamp: str) -> str:
        return self._append('observed-absent', operation, timestamp)

    def complete(self, expected_operations: tuple[str, ...], timestamp: str) -> str:
        return self._append('phase-complete', 'phase', timestamp, expected_operations)

    def close(self):
        for name in ('marker_fd','directory_fd'):
            fd = getattr(self, name, None)
            if fd is not None: os.close(fd); setattr(self, name, None)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
