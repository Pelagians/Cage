"""Relocatable private ELF interpreters; no consumer patchelf or host libc upgrade."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile

# Linux permits PT_INTERP up to PATH_MAX bytes, including the terminating NUL.
# Export reserves space; launch changes only these bytes in temporary copies.
INTERPRETER_PLACEHOLDER = '/CAGE_PRIVATE_LOADER_' + '.' * (4095 - len('/CAGE_PRIVATE_LOADER_'))


def interpreter_slot(path):
    with Path(path).open('rb') as handle:
        header = handle.read(64)
        if header[:4] != b'\x7fELF':
            return None
        if len(header) != 64 or header[4:6] != b'\x02\x01':
            raise ValueError('private runtime requires ELF64 little-endian: ' + str(path))
        offset = struct.unpack_from('<Q', header, 32)[0]
        size, count = struct.unpack_from('<HH', header, 54)
        if size != 56 or count > 1024:
            raise ValueError('invalid ELF program headers: ' + str(path))
        for index in range(count):
            handle.seek(offset + size * index)
            program = handle.read(size)
            if len(program) != size:
                raise ValueError('truncated ELF program header')
            if struct.unpack_from('<I', program)[0] == 3:  # PT_INTERP
                start, length = struct.unpack_from('<Q', program, 8)[0], struct.unpack_from('<Q', program, 32)[0]
                if not 1 < length <= 4096 or start + length > os.fstat(handle.fileno()).st_size:
                    raise ValueError('invalid ELF interpreter slot')
                return start, length
    return None


def materialize(source, destination, manifest):
    """Mirror immutable files, copying only executables that need PT_INTERP edits."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if manifest.get('schemaVersion') != 'cage.appimage-private-runtime/v1':
        raise ValueError('unsupported AppImage private runtime')
    paths = {}
    for entry in manifest['executables']:
        relative = Path(entry['path'])
        if relative.is_absolute() or '..' in relative.parts or relative.parts[:1] != ('usr',) or relative in paths:
            raise ValueError('unsafe private executable path')
        paths[relative] = entry
    loader_relative = Path(manifest['loader'])
    if loader_relative.is_absolute() or '..' in loader_relative.parts or loader_relative.parts[:3] != ('usr', 'lib', 'cage-native'):
        raise ValueError('unsafe private loader path')
    loader = source / loader_relative
    if not loader.resolve().is_relative_to(source) or not loader.is_file():
        raise ValueError('missing private loader')
    interpreter = os.fsencode(loader) + b'\0'
    directories = {parent for relative in paths for parent in relative.parents}

    def mirror(root, relative=Path()):
        for path in root.iterdir():
            name = relative / path.name
            target = destination / name
            if name in paths:
                if path.is_symlink() or not path.is_file():
                    raise ValueError('private executable is not a regular file')
                if hashlib.sha256(path.read_bytes()).hexdigest() != paths[name]['sha256']:
                    raise ValueError('private executable digest mismatch: ' + str(name))
                slot = interpreter_slot(path)
                if not slot or len(interpreter) > slot[1]:
                    raise ValueError('private loader path exceeds interpreter slot')
                with path.open('rb') as handle:
                    handle.seek(slot[0])
                    if handle.read(slot[1]) != os.fsencode(INTERPRETER_PLACEHOLDER) + b'\0':
                        raise ValueError('unreserved private interpreter slot')
                shutil.copyfile(path, target)
                with target.open('r+b') as handle:
                    handle.seek(slot[0])
                    handle.write(interpreter.ljust(slot[1], b'\0'))
                target.chmod(path.stat().st_mode & 0o777)
            elif name in directories:
                if path.is_symlink() or not path.is_dir():
                    raise ValueError('unsafe private executable directory')
                target.mkdir()
                mirror(path, name)
            else:
                # Preserve aliases such as bin/wine -> ../lib/.../wine. Absolute
                # links here would bypass the patched copy of the executable.
                target.symlink_to(os.readlink(path) if path.is_symlink() else path,
                                  target_is_directory=path.is_dir())
    mirror(source)
    if any(not (destination / path).is_file() for path in paths):
        raise ValueError('missing private executable')


def bootstrap():
    root = Path(sys.argv[1]).resolve()
    manifest = json.loads((root / 'usr/libexec/private-runtime.json').read_text())
    # mkdtemp supplies an exclusive 0700 tree; no persistent runtime cache can
    # outlive the mounted package or select an older executable after an update.
    with tempfile.TemporaryDirectory(prefix='cage-private-') as temporary:
        runtime = Path(temporary)
        materialize(root, runtime, manifest)
        sys.executable = str(runtime / 'usr/python/bin/python3')
        sys._base_executable = sys.executable
        from appimage_launch import main
        try:
            raise SystemExit(main(runtime, sys.argv[2:]))
        except (OSError, ValueError, KeyError) as exc:
            print('Cage AppImage: ' + str(exc), file=sys.stderr)
            raise SystemExit(1)
