#!/usr/bin/python3
"""Shared native Wine task startup; hosted x86 sessions retain their own /init."""
import base64
import os
from pathlib import Path
import pwd
import platform
import select
import signal
import subprocess
import sys


def main():
    if platform.machine() == 'aarch64' and os.sysconf("SC_PAGE_SIZE") not in {4096, 16384}:
        raise SystemExit("ARM64EC runtime qualifies 4 KB and 16 KB kernels only")
    mode = os.environ.get("CAGE_SESSION_MODE", "headless")
    if mode not in {"build", "headless", "desktop"}:
        raise SystemExit("native Wine tasks support build, headless and desktop X11")
    uid, gid = int(os.environ.get("PUID", "1000")), int(os.environ.get("PGID", "1000"))
    if uid <= 0 or gid <= 0:
        raise SystemExit("native Wine tasks require non-root PUID/PGID")
    if os.geteuid() == 0:
        try:
            account = pwd.getpwuid(uid)
        except KeyError:
            try:
                pwd.getpwnam('abc')
            except KeyError:
                subprocess.run(["groupadd", "-o", "-g", str(gid), "abc"], check=True)
                subprocess.run(["useradd", "-o", "-u", str(uid), "-g", str(gid), "-m", "abc"], check=True)
            else:
                # Universal x86 images already have abc; match the explicit
                # caller IDs without starting the hosted desktop services.
                subprocess.run(['groupmod', '-o', '-g', str(gid), 'abc'], check=True)
                subprocess.run(['usermod', '-o', '-u', str(uid), '-g', str(gid), 'abc'], check=True)
            account = pwd.getpwuid(uid)
        for directory in ("/var/lib/cage/state", "/var/lib/cage/state/home", "/exports"):
            path = Path(directory)
            path.mkdir(parents=True, exist_ok=True)
            os.chown(path, uid, gid)
        Path("/tmp/.X11-unix").mkdir(mode=0o1777, exist_ok=True)
        runtime_directory = Path(f"/tmp/cage-runtime-{uid}")
        runtime_directory.mkdir(mode=0o700, exist_ok=True)
        os.chown(runtime_directory, uid, gid)
        if mode != "desktop":
            Path("/tmp/.X11-unix").chmod(0o1777)
        def demote():
            os.setgroups([])
            os.setgid(gid)
            os.setuid(uid)
    else:
        account = pwd.getpwuid(os.getuid())
        demote = None
    home = "/var/lib/cage/state/home"
    env = {**os.environ, "HOME": home, "USER": account.pw_name, "LOGNAME": account.pw_name,
           "XDG_CACHE_HOME": home + "/.cache", "XDG_CONFIG_HOME": home + "/.config",
           "XDG_RUNTIME_DIR": f"/tmp/cage-runtime-{uid}"}
    if mode == "build":
        env.setdefault("WINEPREFIX", env.get("CAGE_BUILD_PREFIX", "/tmp/cage-build-prefix"))
    env.pop("WAYLAND_DISPLAY", None)
    server = None
    if mode != "desktop":
        read_fd, write_fd = os.pipe()
        try:
            server = subprocess.Popen(["Xvfb", "-displayfd", str(write_fd), "-screen", "0", "1280x900x24", "-nolisten", "tcp", "-noreset"],
                                      pass_fds=(write_fd,), preexec_fn=demote, env=env)
            os.close(write_fd)
            write_fd = None
            if not select.select([read_fd], [], [], 30)[0]:
                raise RuntimeError("Xvfb startup timed out")
            display = os.read(read_fd, 32).decode().strip()
            if not display.isdecimal():
                raise RuntimeError("Xvfb did not report a display")
            env["DISPLAY"] = ":" + display
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)
    elif not env.get("DISPLAY"):
        raise SystemExit("desktop mode requires an explicitly shared X11 display")
    encoded = env.get("CAGE_BUILD_SCRIPT_B64" if mode == "build" else "CAGE_LAUNCH_SCRIPT_B64")
    command = (["bash", "-c", base64.b64decode(encoded, validate=True).decode()] if encoded
               else [env["CAGE_APP_LAUNCHER"], *sys.argv[1:]] if env.get("CAGE_APP_LAUNCHER") else sys.argv[1:])
    if not command:
        raise SystemExit("no Cage task supplied")
    child = None
    try:
        child = subprocess.Popen(command, env=env, preexec_fn=demote, start_new_session=True)
        def terminate(*_):
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        signal.signal(signal.SIGTERM, terminate)
        signal.signal(signal.SIGINT, terminate)
        code = child.wait()
        if mode == "build":
            receipt = Path("/opt/cage/logs/container-exit-code")
            receipt.write_text(str(code) + "\n")
            if os.geteuid() == 0:
                os.chown(receipt, uid, gid)
        return code
    finally:
        subprocess.run(["wineserver", "-k"], env=env, preexec_fn=demote, timeout=15, check=False)
        if server is not None:
            server.terminate()
            server.wait(timeout=15)


if __name__ == "__main__":
    raise SystemExit(main())
