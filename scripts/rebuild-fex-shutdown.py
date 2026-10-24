#!/usr/bin/env python3
"""Reproduce the bundled ARM64EC DLL; build tools are never consumer requirements.

Run on aarch64 Linux with Python, git, cmake and ninja. All translator sources,
submodules, provider patches and the compiler are pinned in source.json.
"""
from pathlib import Path
import argparse
import hashlib
import json
import lzma
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'runtime/vendor/fex-2610-cage1'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download(item, path, limit):
    with urllib.request.urlopen(item['url'], timeout=120) as response, path.open('xb') as output:
        count = 0
        while chunk := response.read(1024 * 1024):
            count += len(chunk)
            if count > limit:raise RuntimeError('source download exceeds size bound')
            output.write(chunk)
    if digest(path) != item['sha256']:raise RuntimeError('source checksum mismatch: ' + item['url'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, help='new dedicated build directory; retained for inspection')
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    if platform.machine() != 'aarch64' or not 1 <= args.jobs <= 8:
        raise RuntimeError('requires native aarch64 Linux and 1-8 build jobs')
    for tool in ('git', 'cmake', 'ninja'):
        if not shutil.which(tool):raise RuntimeError('build tool missing: ' + tool)
    lock = json.loads((VENDOR / 'source.json').read_text())
    patch = (VENDOR / lock['patch']['path']).resolve()
    if digest(patch) != lock['patch']['sha256']:raise RuntimeError('local source patch changed')
    # A caller-selected directory must be new; never reset a user's checkout.
    work = args.work.resolve() if args.work else Path(tempfile.mkdtemp(prefix='cage-fex-rebuild-'))
    if args.work:work.mkdir(parents=True, exist_ok=False)
    print('Build directory: ' + str(work), flush=True)
    env = dict(os.environ, SOURCE_DATE_EPOCH=str(lock['sourceDateEpoch']))
    def run(command):
        subprocess.run(command, env=env, check=True)
    archive = work / 'toolchain.tar.xz'
    download(lock['toolchain'], archive, 80 * 1024**2)
    with tarfile.open(archive) as source:
        if sum(item.size for item in source.getmembers()) > 1024**3:
            raise RuntimeError('compiler extraction exceeds size bound')
        source.extractall(work, filter='data')
    env['PATH'] = str(work / lock['toolchain']['directory'] / 'bin') + os.pathsep + env['PATH']
    source = work / 'FEX'
    run(['git', 'init', str(source)])
    run(['git', '-C', str(source), 'remote', 'add', 'origin', lock['source']['url']])
    run(['git', '-C', str(source), 'fetch', '--depth=1', 'origin', lock['source']['commit']])
    run(['git', '-C', str(source), 'checkout', '--detach', 'FETCH_HEAD'])
    actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != lock['source']['commit']:raise RuntimeError('translator source identity mismatch')
    run(['git', '-C', str(source), 'submodule', 'update', '--init', '--depth=1', '--', *lock['submodules']])
    for index, item in enumerate(lock['providerPatches']):
        path = work / ('provider-' + str(index) + '.patch')
        download(item, path, 256 * 1024)
        run(['git', '-C', str(source), 'apply', str(path)])
    run(['git', '-C', str(source), 'apply', str(patch)])
    build = work / 'build'
    run(['cmake', '-S', str(source), '-B', str(build), '-GNinja',
         '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_TOOLCHAIN_FILE=' + str(source / 'Data/CMake/toolchain_mingw.cmake'),
         '-DMINGW_TRIPLE=arm64ec-w64-mingw32', '-DENABLE_LTO=OFF', '-DTUNE_CPU=none',
         '-DBUILD_TESTING=OFF', '-DENABLE_JEMALLOC_GLIBC_ALLOC=OFF', '-DCMAKE_POLICY_VERSION_MINIMUM=3.5',
         '-DCMAKE_C_FLAGS=-O3', '-DCMAKE_CXX_FLAGS=-O3',
         '-DOVERRIDE_VERSION=' + lock['source']['version'], '-DOVERRIDE_HASH=' + actual])
    ninja = build / 'build.ninja'
    ninja.write_text(ninja.read_text().replace('arm64ec-w64-mingw32-dlltool', 'llvm-dlltool -m arm64ec'))
    run(['ninja', '-C', str(build), '-j' + str(args.jobs), 'arm64ecfex'])
    dll = build / 'Bin/libarm64ecfex.dll'
    bundled = lzma.decompress((VENDOR / lock['dll']['path']).read_bytes())
    if (digest(dll) != lock['dll']['sha256'] or dll.read_bytes() != bundled):
        raise RuntimeError('rebuild differs from bundled DLL; retained build requires review')
    print(json.dumps({'reproduced': True, 'sha256': digest(dll), 'source': actual, 'work': str(work)}))


if __name__ == '__main__':main()
