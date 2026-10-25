"""Evidence shared by the real AppImage consumer proofs."""
import os
import subprocess


def consumer_glibc(image):
    value = subprocess.check_output(['podman', 'run', '--rm', '--network', 'none', image,
                                     'getconf', 'GNU_LIBC_VERSION'], text=True).strip()
    expected = os.environ.get('CAGE_TEST_EXPECT_GLIBC')
    if expected and value != 'glibc ' + expected:
        raise AssertionError('unexpected consumer libc: ' + value)
    return value


def private_runtime_maps(container):
    script = '''for proc in /proc/[0-9]*; do
        exe=$(readlink "$proc/exe") || continue
        case "$exe" in
            *cage-private*|*usr/lib/cage-native/ld-linux*)
                printf '%s %s\\n' "$proc" "$exe"
                grep '/libc.so.6' "$proc/maps" ;;
        esac
    done'''
    maps = subprocess.check_output(['podman', 'exec', container, 'sh', '-c', script], text=True)
    assert '/usr/wine/' in maps and 'wineserver' in maps, maps
    libc = [line for line in maps.splitlines() if '/libc.so.6' in line]
    assert libc and all('/usr/lib/cage-native/libc.so.6' in line for line in libc), maps
    return maps
