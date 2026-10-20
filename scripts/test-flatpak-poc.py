#!/usr/bin/env python3
"""Real installed Notepad++ GUI workflow; requires an X11 test desktop."""
from pathlib import Path
import json
import os
import subprocess
import time
import xml.etree.ElementTree as ET
import configparser

APP = "io.github.Pelagians.Cage.NotepadPlusPlus"
ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "dist/desktop-evidence"


def command(*argv):
    return subprocess.check_output(argv, text=True, timeout=30).strip()


def wait_for(function, description, seconds=120):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            result = function()
            if result:
                return result
        except (OSError, subprocess.CalledProcessError):
            pass
        time.sleep(0.5)
    raise AssertionError("timed out: " + description)


def window():
    return command("xdotool", "search", "--onlyvisible", "--name", "Notepad\\+\\+").splitlines()[-1]


def launch(desktop, document):
    subprocess.run(["gio", "launch", str(desktop), str(document)], check=True)
    handle = wait_for(window, "real Notepad++ window")
    command("xdotool", "windowactivate", "--sync", handle)
    return handle


def close_application():
    command("xdotool", "key", "--clearmodifiers", "alt+F4")
    wait_for(lambda: APP not in command("flatpak", "ps", "--columns=application"), "application shutdown")


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    home = Path.home()
    docs = home / "Documents/Cage"
    docs.mkdir(parents=True, exist_ok=True)
    document = docs / "Desktop proof café.txt"
    document.write_text("Original document\n")
    user_store = Path(os.environ["FLATPAK_USER_DIR"])
    desktop = user_store / "exports/share/applications" / (APP + ".desktop")
    assert desktop.is_file(), "installed desktop entry missing"
    permissions = command("flatpak", "info", "--user", "--show-permissions", APP)
    permission_data = configparser.ConfigParser()
    permission_data.read_string(permissions)
    assert "network" not in permission_data.get("Context", "shared", fallback="").split(";"), permissions
    assert "filesystems=xdg-documents/Cage:create;" in permissions, permissions
    (EVIDENCE / "permissions.txt").write_text(permissions + "\n")
    immutable = command("flatpak", "info", "--user", "--show-commit", APP)
    launch(desktop, document)
    command("xdotool", "key", "--clearmodifiers", "ctrl+a")
    command("xdotool", "type", "--clearmodifiers", "--delay", "15", "Cage Flatpak saved through the real application")
    command("xdotool", "key", "--clearmodifiers", "Return", "ctrl+s", "ctrl+KP_Add")
    wait_for(lambda: "Cage Flatpak saved" in document.read_text(), "application saved host document")
    subprocess.run(["scrot", str(EVIDENCE / "first-launch-saved.png")], check=True)
    close_application()
    prefix = home / ".var/app" / APP / "data" / APP / "prefix"
    config = prefix / "drive_c/Program Files/Notepad++/config.xml"
    wait_for(config.exists, "persisted application settings")
    original_config = ET.parse(config).getroot()
    zoom = original_config.find(".//GUIConfig[@name='ScintillaPrimaryView']").attrib["zoom"]
    assert zoom != "0", "GUI zoom change was not persisted"
    state_path = prefix.parent / "state.json"
    state_before = state_path.read_bytes()
    launch(desktop, document)
    # Ctrl+A then copy lets the test read exactly what the reopened editor holds.
    command("xdotool", "key", "--clearmodifiers", "ctrl+a", "ctrl+c")
    reopened = command("xclip", "-selection", "clipboard", "-o")
    assert "Cage Flatpak saved through the real application" in reopened, reopened
    subprocess.run(["scrot", str(EVIDENCE / "relaunch-reopened.png")], check=True)
    close_application()
    assert state_before == state_path.read_bytes(), "prefix was reinitialized"
    assert ET.parse(config).getroot().find(".//GUIConfig[@name='ScintillaPrimaryView']").attrib["zoom"] == zoom
    assert command("flatpak", "info", "--user", "--show-commit", APP) == immutable
    # Verify the mounted seed is still sealed after actual application use.
    subprocess.run(["flatpak", "run", "--command=python3", APP, "-c",
        "import json,sys;sys.path.insert(0,'/app/libexec');import importlib.util;"
        "s=importlib.util.spec_from_file_location('launch','/app/libexec/cage-desktop-launch.py');"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        "from pathlib import Path;p=Path('/app/share/cage/" + APP + "');"
        "m.verify_inventory(p/'seed',json.loads((p/'seed-inventory.json').read_text()))"], check=True)
    result = {"schemaVersion": "cage.desktop-functional-test/v0", "status": "passed", "appId": APP,
              "packageCommit": immutable, "install": True, "desktopLaunch": True, "save": True,
              "relaunch": True, "reopenedEditorContents": reopened, "settingsZoom": zoom,
              "sameStateGeneration": True, "immutableSeedVerified": True,
              "session": "Xvfb X11 with Openbox", "applicationVersion": "8.8.8"}
    (EVIDENCE / "functional-test.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        subprocess.run(["scrot", str(EVIDENCE / "failure.png")], check=False)
        raise
