"""AppImage-only host integration; application lifecycle lives in desktop_launch."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from desktop_launch import DesktopError, launch


def file_hash(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def desktop_quote(value):
    value = str(value).replace('%', '%%')
    for character in ('\\', '"', '`', '$'):
        value = value.replace(character, '\\' + character)
    return '"' + value + '"'


def integrate(root, plan, *, remove=False):
    """Explicit per-user integration; never register associations or erase state."""
    data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))).resolve()
    app_id = plan['desktop']['id']
    directory = data / 'cage/appimages' / app_id
    package = directory / 'application.AppImage'
    receipt = directory / 'installation.json'
    desktop = data / 'applications' / (app_id + '.CageAppImage.desktop')
    icon = data / 'icons/hicolor/scalable/apps' / (app_id + '.CageAppImage.svg')
    if remove:
        if receipt.is_symlink() or not receipt.is_file():
            raise DesktopError('no Cage AppImage installation receipt; files retained')
        recorded = json.loads(receipt.read_text())
        expected = {'package': package, 'desktop': desktop, 'icon': icon}
        for name, path in expected.items():
            if path.is_symlink() or not path.is_file() or file_hash(path) != recorded.get(name):
                raise DesktopError('installed files changed; retain them for manual recovery')
        for path in expected.values():
            path.unlink()
        receipt.unlink()
        directory.rmdir()
        return {'removed': True, 'userStateRetained': True}
    source = Path(os.environ.get('APPIMAGE', ''))
    if not source.is_file():
        raise DesktopError('desktop installation requires the original .AppImage, not an extracted AppDir')
    with source.open('rb') as handle:
        if handle.read(4) != b'\x7fELF':
            raise DesktopError('desktop installation requires the original .AppImage')
    if any(path.exists() or path.is_symlink() for path in (directory, desktop, icon)):
        raise DesktopError('AppImage desktop installation already exists; upgrades are not implemented')
    directory.mkdir(parents=True, mode=0o700)
    try:
        shutil.copyfile(source, package)
        package.chmod(0o755)
        desktop.parent.mkdir(parents=True, exist_ok=True)
        icon.parent.mkdir(parents=True, exist_ok=True)
        icon.write_bytes((root / (app_id + '.svg')).read_bytes())
        metadata = plan['desktop']
        desktop.write_text('[Desktop Entry]\nType=Application\n'
            + 'Name=' + metadata['name'].replace('\\', '\\\\') + ' (AppImage)\n'
            + 'Comment=' + metadata['summary'].replace('\\', '\\\\') + '\n'
            + 'Exec=' + desktop_quote(package) + ' -- %F\n'
            + 'Icon=' + app_id + '.CageAppImage\n'
            + 'Categories=' + ';'.join(metadata['categories']) + ';\nTerminal=false\n')
        receipt.write_text(json.dumps({name: file_hash(path) for name, path in
                           {'package': package, 'desktop': desktop, 'icon': icon}.items()}, sort_keys=True) + '\n')
    except BaseException:
        # All paths were absent before this explicit installation.
        for path in (desktop, icon, package, receipt):
            path.unlink(missing_ok=True)
        directory.rmdir()
        raise
    return {'installed': str(package), 'desktop': str(desktop), 'userStateRetained': True}


def main(root, arguments):
    root = Path(root).resolve()
    plans = list((root / 'usr/share/cage').glob('*/desktop.json'))
    if len(plans) != 1:
        raise DesktopError('missing or ambiguous application metadata')
    metadata = plans[0]
    plan = json.loads(metadata.read_text())
    if platform.machine() != plan['target']['architecture']:
        raise DesktopError('this AppImage was built for ' + plan['target']['architecture'])
    if arguments == ['--cage-info']:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    if arguments in (['--cage-install'], ['--cage-uninstall']):
        print(json.dumps(integrate(root, plan, remove=arguments == ['--cage-uninstall']), indent=2))
        return 0
    if arguments[:1] == ['--']:
        arguments = arguments[1:]
    elif arguments and arguments[0].startswith('--cage-'):
        raise DesktopError('unknown Cage AppImage option')
    return launch(metadata, arguments)


if __name__ == '__main__':
    try:
        raise SystemExit(main(sys.argv[1], sys.argv[2:]))
    except (DesktopError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print('Cage AppImage: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
