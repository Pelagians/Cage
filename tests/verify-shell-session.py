#!/usr/bin/env python3
"""Check a real consumer window through Labwc IPC, not process existence."""
import argparse
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time


def command(*args, env=None, input=None):
    return subprocess.check_output(args, env=env, input=input, text=True, timeout=15)


def verify(state, health, pattern):
    assert health["adapter_connected"] and health["layoutd"] == "healthy", health
    assert health["reconciliation"] == "healthy", health
    normals = [v for v in state["views"] if v["type"] == "normal" and v["parent_id"] is None]
    assert len(normals) == 1, state
    view = normals[0]
    assert re.search(pattern, view["app_id"] + " " + view["title"], re.I), view
    assert health["managed_windows"] == 1, health
    assert view["decoration"] == "full" and view["titlebar_visible"], view
    assert view["maximized"] and not view["fullscreen"] and not view["minimized"], view
    assert not view["tiled"] and view["region"] == "", view
    area = state["outputs"][0]["usable_area"]
    assert (area["width"], area["height"]) == (1920, 1080), area
    assert all(view[k] == area[k] for k in ("x", "y", "width", "height")), (view, area)
    return view


def snapshot():
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(3)
        client.connect("/config/.XDG/labwc.sock")
        client.sendall(b"LIST\n")
        chunks = []
        while chunk := client.recv(65536):
            chunks.append(chunk)
    return json.loads(b"".join(chunks))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pattern")
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--keyring", choices=("store", "lookup"))
    args = parser.parse_args()
    deadline = time.monotonic() + 180
    while True:
        try:
            state = snapshot()
            health = json.loads(command("pelagian-layoutd", "status"))
            view = verify(state, health, args.pattern)
            break
        except (AssertionError, OSError, ValueError, subprocess.SubprocessError) as error:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"consumer layout did not converge: {error}") from error
            time.sleep(1)
    if args.native or args.keyring:
        # Read only the session coordinates needed for child commands. Never log
        # the process environment, which can contain application credentials.
        entries = Path(f"/proc/{view['pid']}/environ").read_bytes().split(b"\0")
        selected = {"DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"}
        env = dict(os.environ)
        for entry in entries:
            key, sep, value = entry.partition(b"=")
            if sep and key.decode() in selected:
                env[key.decode()] = value.decode()
        if args.native:
            assert env.get("WAYLAND_DISPLAY") and env.get("DISPLAY"), "missing application display coordinates"
            wayland = command("wlrctl", "toplevel", "list", env=env)
            x11 = command("xlsclients", "-display", env["DISPLAY"], "-l", env=env)
            assert re.search(args.pattern, wayland, re.I), wayland
            assert not re.search(args.pattern, x11, re.I), x11
        if args.keyring:
            assert env.get("DBUS_SESSION_BUS_ADDRESS"), "missing application session bus"
            attributes = ("application", "grotto-shell-ci", "purpose", "restart-persistence")
            secret = "ephemeral-ci-secret"
            if args.keyring == "store":
                command("secret-tool", "store", "--label=Grotto CI restart check", *attributes, env=env, input=secret)
            assert command("secret-tool", "lookup", *attributes, env=env).strip() == secret, "keyring value did not survive"
    print(f"consumer layout: {args.pattern}, maximized with visible titlebar, 1920x1080, healthy")


if __name__ == "__main__":
    main()
