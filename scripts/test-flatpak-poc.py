#!/usr/bin/env python3
"""Real installed Notepad++ GUI workflow; requires an X11 test desktop."""
from pathlib import Path
import json
import os
import subprocess
import time
import xml.etree.ElementTree as ET
import configparser
import shutil

APP = "io.github.Pelagians.Cage.NotepadPlusPlus"
ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(os.environ.get("CAGE_TEST_EVIDENCE", str(ROOT / "dist/desktop-evidence")))


def command(*argv):
    return subprocess.check_output(argv, text=True, timeout=30).strip()


def wait_for(function, description, seconds=120):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            result = function()
            if result:
                return result
        except (OSError, subprocess.SubprocessError):
            pass
        time.sleep(0.5)
    raise AssertionError("timed out: " + description)


def window():
    return command("xdotool", "search", "--onlyvisible", "--name", "Notepad\\+\\+").splitlines()[-1]


def focus_editor(handle):
    """Focus the real editor after load, not just the Wine top-level window."""
    command("xdotool", "windowactivate", "--sync", handle)
    wait_for(lambda: command("xdotool", "getactivewindow") == handle, "application activation")
    geometry = dict(line.split("=", 1) for line in
                    command("xdotool", "getwindowgeometry", "--shell", handle).splitlines())
    # The pinned Notepad++ default layout puts the editor in the client center.
    # A top-level activation alone can precede Scintilla's first focus event.
    command("xdotool", "mousemove", "--window", handle,
            str(int(geometry["WIDTH"]) // 2), str(int(geometry["HEIGHT"]) // 2))
    command("xdotool", "click", "--clearmodifiers", "1")


def launch(desktop, document):
    subprocess.run(["gio", "launch", str(desktop), str(document)], check=True)
    handle = wait_for(window, "real Notepad++ window")
    wait_for(lambda: document.name in command("xdotool", "getwindowname", handle), "requested document loaded")
    focus_editor(handle)
    return handle


def close_application():
    command("xdotool", "key", "--clearmodifiers", "alt+F4")
    def no_window():
        return subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "Notepad\\+\\+"],
                              capture_output=True, timeout=10).returncode != 0
    wait_for(no_window, "application window closed without a save prompt", seconds=30)
    wait_for(lambda: APP not in command("flatpak", "ps", "--columns=application"), "application shutdown", seconds=45)


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    home = Path.home()
    docs = home / "Documents/Cage"
    docs.mkdir(parents=True, exist_ok=True)
    document = docs / os.environ.get("CAGE_TEST_DOCUMENT", "Desktop proof café.txt")
    document.write_text("Original document\n")
    user_store = Path(os.environ["FLATPAK_USER_DIR"])
    desktop = user_store / "exports/share/applications" / (APP + ".desktop")
    assert desktop.is_file(), "installed desktop entry missing"
    installed_apps = command("flatpak", "list", "--user", "--app", "--columns=application").splitlines()
    assert installed_apps == [APP], installed_apps
    permissions = command("flatpak", "info", "--user", "--show-permissions", APP)
    permission_data = configparser.ConfigParser()
    permission_data.read_string(permissions)
    assert "network" not in permission_data.get("Context", "shared", fallback="").split(";"), permissions
    assert "filesystems=xdg-documents/Cage:create;" in permissions, permissions
    (EVIDENCE / "permissions.txt").write_text(permissions + "\n")
    print("Installed application and permissions verified", flush=True)
    immutable = command("flatpak", "info", "--user", "--show-commit", APP)
    handle = launch(desktop, document)
    print("Installed desktop entry opened the requested document", flush=True)
    command("xdotool", "key", "--clearmodifiers", "ctrl+a")
    command("xdotool", "type", "--clearmodifiers", "--delay", "15", "Cage Flatpak saved through the real application")
    command("xdotool", "key", "--clearmodifiers", "Return", "ctrl+s")
    expected = "Cage Flatpak saved through the real application\n"
    wait_for(lambda: document.read_text() == expected, "application saved exact host document contents")
    # Pinned 8.8.8 English resource: View's seventh selectable item is Zoom.
    # Use the actual menu command rather than an Xvfb keypad/modifier mapping.
    command("xdotool", "key", "--clearmodifiers", "alt+v")
    command("xdotool", "key", "--delay", "80", "Home", *(["Down"] * 6), "Right", "Home")
    subprocess.run(["scrot", str(EVIDENCE / "zoom-menu.png")], check=True)
    command("xdotool", "key", "Return")
    command("xdotool", "key", "--clearmodifiers", "ctrl+s")
    wait_for(lambda: document.read_text() == expected and not command("xdotool", "getwindowname", handle).startswith("*"),
             "document is unchanged by zoom and has no unsaved marker")
    print("Real application saved the edited document", flush=True)
    subprocess.run(["scrot", str(EVIDENCE / "first-launch-saved.png")], check=True)
    close_application()
    print("Application and its Wine services stopped", flush=True)
    prefix = home / ".var/app" / APP / "data" / APP / "prefix"
    # Pinned Notepad++ disables doLocalConf.xml under Program Files (UAC),
    # even for the portable archive. Inspect its actual per-user settings.
    configs = list(prefix.glob("drive_c/users/*/AppData/Roaming/Notepad++/config.xml"))
    assert len(configs) == 1, f"expected one active Notepad++ user configuration: {configs}"
    config = configs[0]
    shutil.copyfile(config, EVIDENCE / "persisted-config.xml")
    original_config = ET.parse(config).getroot()
    zoom = original_config.find(".//GUIConfig[@name='ScintillaPrimaryView']").attrib["zoom"]
    assert zoom != "0", "GUI zoom change was not persisted"
    state_path = prefix.parent / "state.json"
    state_before = state_path.read_bytes()
    launch(desktop, document)
    # Appending through the reopened editor and checking the whole saved file
    # proves it loaded the previous contents, without a host clipboard dependency.
    command("xdotool", "key", "--clearmodifiers", "ctrl+End")
    command("xdotool", "type", "--clearmodifiers", "--delay", "15", "Relaunch verified")
    command("xdotool", "key", "--clearmodifiers", "Return", "ctrl+s")
    second_expected = expected + "Relaunch verified\n"
    wait_for(lambda: document.read_text() == second_expected, "reopened editor preserved and extended saved text", seconds=30)
    print("Relaunched application reopened, extended and saved the original text", flush=True)
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
    runtime_ref = command("flatpak", "info", "--user", "--show-runtime", APP)
    # The app may resolve its shared runtime from a system installation.
    # Inspect the actual mounted instance rather than assuming user scope.
    instance = configparser.ConfigParser()
    instance.read_string(command("flatpak", "run", "--command=cat", APP, "/.flatpak-info"))
    runtime_commit = instance.get("Instance", "runtime-commit")
    wine_version = command("flatpak", "run", "--command=wine", APP, "--version")
    assert wine_version == os.environ.get("CAGE_TEST_WINE_VERSION", "wine-11.0"), wine_version
    result = {"schemaVersion": "cage.desktop-functional-test/v0", "status": "passed", "appId": APP,
              "packageCommit": immutable, "install": True, "desktopLaunch": True, "save": True,
              "relaunch": True, "secondSaveContents": document.read_text(), "settingsZoom": zoom,
              "settingsPath": str(config.relative_to(prefix)),
              "sameStateGeneration": True, "immutableSeedVerified": True,
              "session": "Xvfb X11 with Openbox", "applicationVersion": "8.8.8",
              "runtimeRef": runtime_ref, "runtimeCommit": runtime_commit, "wineVersion": wine_version,
              "host": command("uname", "-srmo"), "flatpakVersion": command("flatpak", "--version")}
    result["kernelPageSize"] = os.sysconf("SC_PAGE_SIZE")
    result["installedRef"] = command("flatpak", "info", "--user", "--show-ref", APP)
    (EVIDENCE / "functional-test.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        subprocess.run(["scrot", str(EVIDENCE / "failure.png")], check=False)
        subprocess.run(["flatpak", "kill", APP], check=False, timeout=30)
        raise
