"""Retire runtime copies belonging to one fresh, successful GUI proof only."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat

from artifact.storage import directory_fd, real_path, read_json, _entry
from runtime.desktop_launch import _read_generations


class ProofPayloads:
    def __init__(self, state, evidence):
        self.state, self.evidence = real_path(state), real_path(evidence)
        if self.state.exists():
            raise ValueError('proof cleanup requires fresh private state; existing state retained')
        # Flatpak must keep disposable state inside its own sandbox namespace.
        private_flatpak = (
            self.state.parent.parent == Path.home() / '.var/app' / self.state.name / 'data'
            and re.fullmatch(r'cage-(?:update|onboarding)-proof-[a-f0-9]{32}', self.state.parent.name))
        if not self.state.is_relative_to(self.evidence) and not private_flatpak:
            raise ValueError('proof state must be inside its evidence workspace or a private Flatpak token')
        self.entries = {}
        self.identity = None
        value = os.environ.get('CAGE_TEST_DISCARD_PREFIXES', '1')
        if value not in {'0', '1'}:
            raise ValueError('CAGE_TEST_DISCARD_PREFIXES must be 0 or 1')
        self.enabled = value == '1'

    @contextmanager
    def locked(self):
        root = real_path(self.state)
        info = root.stat()
        identity = (info.st_dev, info.st_ino)
        if self.identity is not None and self.identity != identity:
            raise ValueError('proof state was replaced; payload retained')
        with directory_fd(root) as parent:
            fd = os.open('launch.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError('invalid proof lifecycle lock')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.identity = identity
            yield
        finally:
            os.close(fd)

    def record(self):
        """Capture runtime binaries only after a normal application shutdown."""
        if not self.enabled:
            return
        with self.locked():
            record = _read_generations(self.state)
            if not record:
                raise ValueError('proof has no committed state; payload retained')
            for generation in record['generations']:
                prefix = real_path(self.state / generation['prefix'])
                for subdir in ('system32', 'syswow64'):
                    base = prefix / 'drive_c/windows' / subdir
                    if not base.exists():
                        continue
                    real_path(base)
                    for folder, dirs, files in os.walk(base, followlinks=False):
                        dirs[:] = sorted(n for n in dirs if not (Path(folder) / n).is_symlink())
                        for name in sorted(files):
                            path = Path(folder) / name
                            if path.suffix.lower() not in {'.dll', '.exe', '.drv', '.cpl', '.ocx', '.sys'}:
                                continue
                            info = path.lstat()
                            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                                continue
                            relative = path.relative_to(self.state).as_posix()
                            if relative in self.entries:
                                continue
                            with path.open('rb') as stream:
                                if stream.read(2) != b'MZ':
                                    continue
                            with directory_fd(path.parent) as parent:
                                entry = _entry(parent, name)
                            if not stat.S_ISREG(entry['stat'][2]):
                                continue
                            self.entries[relative] = entry

    def finish(self):
        """Called after all assertions and qualification records were saved."""
        result = {'schemaVersion': 'cage.proof-payload-cleanup/v1', 'state': str(self.state),
                  'status': 'retained', 'removedFiles': [], 'savedDataAndPackagesRetained': True}
        receipt = self.evidence / 'payload-cleanup.json'
        inventory = self.evidence / 'runtime-payload-inventory.json'
        journal = self.evidence / 'removed-runtime-files.log'
        retirement = self.state / 'retired-test-payload.json'
        # Refuse old evidence before creating records or removing any payload.
        for path in (receipt, inventory, journal, retirement):
            if real_path(path).exists():
                raise ValueError('existing cleanup evidence; payload retained: ' + str(path))
        if self.enabled and self.identity is None:
            raise ValueError('no stopped proof payload was recorded; state retained')
        if not self.enabled:
            result['reason'] = 'CAGE_TEST_DISCARD_PREFIXES=0'
        elif not self.entries:
            result['reason'] = 'no independent runtime copies to remove'
        else:
            with self.locked():
                qualifications = [self.evidence / name for name in ('result.json', 'functional-test.json')
                                  if (self.evidence / name).exists() or (self.evidence / name).is_symlink()]
                if not qualifications or any(read_json(path).get('status') != 'passed' for path in qualifications):
                    raise ValueError('saved passing qualification required; payload retained')
                # Revalidate the entire removal set before starting any deletion.
                for relative, expected in self.entries.items():
                    path = real_path(self.state / relative)
                    with directory_fd(path.parent) as parent:
                        if _entry(parent, path.name) != expected or path.stat().st_nlink != 1:
                            raise ValueError('proof payload changed; retained: ' + relative)
                with inventory.open('x') as handle:
                    handle.write(json.dumps(self.entries, sort_keys=True) + '\n')
                # Persist qualification and complete inventory before retirement.
                with directory_fd(self.evidence) as parent:
                    for path in (inventory, *qualifications):
                        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
                        try:
                            os.fsync(fd)
                        finally:
                            os.close(fd)
                    os.fsync(parent)
                before = shutil.disk_usage(self.state).free
                # The existing CI collectors retain .log files, including a
                # partial JSON-lines journal from an interrupted cleanup.
                with journal.open('x') as log:
                    for relative, expected in self.entries.items():
                        path = real_path(self.state / relative)
                        with directory_fd(path.parent) as parent:
                            if _entry(parent, path.name) != expected or path.stat().st_nlink != 1:
                                raise ValueError('proof payload changed; remaining files retained')
                            os.unlink(path.name, dir_fd=parent)
                        log.write(json.dumps({'path': relative, **expected}) + '\n')
                        log.flush()
                        result['removedFiles'].append(relative)
                result.update(status='cleaned', freeBeforeBytes=before,
                              freeAfterBytes=shutil.disk_usage(self.state).free)
                with retirement.open('x') as handle:
                    handle.write(json.dumps({
                        'status': 'retired', 'receipt': str(receipt),
                        'notice': 'Historical test state; runtime copies removed. Settings, documents and state records retained. Not runnable.'
                    }, indent=2) + '\n')
        with receipt.open('x') as handle:
            handle.write(json.dumps(result, indent=2) + '\n')
        return result
