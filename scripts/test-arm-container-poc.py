#!/usr/bin/env python3
"""Real Cage ARM container: writable document and persistent-state GUI proof."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EVIDENCE = ROOT / "dist/arm64-evidence/container"
spec = importlib.util.spec_from_file_location("gui", ROOT / "scripts/test-flatpak-poc.py")
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)


def main():
    bundle = Path(sys.argv[1]).resolve()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    state = Path(os.environ.get("CAGE_TEST_CONTAINER_STATE", str(ROOT / ".cage/arm-container-state")))
    documents = ROOT / ".cage/arm-container-documents"
    documents.mkdir(parents=True, exist_ok=True)
    document = documents / "Container proof café.txt"
    document.write_text("Original container document\n")
    graph = json.loads((bundle / "metadata/graph.json").read_text())
    plan = json.loads((bundle / "metadata/native-launch.json").read_text())
    assert graph["runnerRuntime"]["architecture"] == "aarch64"
    assert plan["target"]["windowsArchitecture"] == "x86_64"
    processes, logs = [], []
    def launch():
        output = (EVIDENCE / f"launch-{len(processes) + 1}.log").open("w")
        logs.append(output)
        process = subprocess.Popen([sys.executable, "-m", "cage", "run", str(bundle), str(document),
            "--engine", "podman", "--graphics", "desktop", "--state-dir", str(state),
            "--writable-files", "--name", "cage-arm-functional", "--timeout", "120"],
            cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
        processes.append(process)
        handle = gui.wait_for(gui.window, "container Notepad++ window", seconds=60)
        gui.wait_for(lambda: document.name in gui.command("xdotool", "getwindowname", handle), "container document loaded", seconds=30)
        gui.focus_editor(handle)
        return process
    def close(process):
        gui.command("xdotool", "key", "--clearmodifiers", "alt+F4")
        assert process.wait(timeout=45) == 0, "Cage container task did not exit successfully"
    try:
        process = launch()
        gui.command("xdotool", "key", "--clearmodifiers", "ctrl+a")
        gui.command("xdotool", "type", "--clearmodifiers", "--delay", "15", "Cage ARM container saved through the real application")
        gui.command("xdotool", "key", "--clearmodifiers", "Return", "ctrl+s")
        expected = "Cage ARM container saved through the real application\n"
        gui.wait_for(lambda: document.read_text() == expected, "container saved exact host document", seconds=30)
        gui.command("xdotool", "key", "--clearmodifiers", "alt+v")
        gui.command("xdotool", "key", "--delay", "80", "Home", *(["Down"] * 6), "Right", "Home", "Return")
        subprocess.run(["scrot", str(EVIDENCE / "first-save.png")], check=True)
        close(process)
        prefix = state / gui.APP / "prefix"
        configs = list(prefix.glob("drive_c/users/*/AppData/Roaming/Notepad++/config.xml"))
        assert len(configs) == 1, configs
        config = configs[0]
        zoom = ET.parse(config).find(".//GUIConfig[@name='ScintillaPrimaryView']").attrib["zoom"]
        assert zoom != "0", "container GUI settings did not persist"
        identity = (prefix.parent / "state.json").read_bytes()
        process = launch()
        gui.command("xdotool", "key", "--clearmodifiers", "ctrl+End")
        gui.command("xdotool", "type", "--clearmodifiers", "--delay", "15", "Container relaunch verified")
        gui.command("xdotool", "key", "--clearmodifiers", "Return", "ctrl+s")
        gui.wait_for(lambda: document.read_text() == expected + "Container relaunch verified\n", "container reopened and extended saved text", seconds=30)
        subprocess.run(["scrot", str(EVIDENCE / "relaunch-save.png")], check=True)
        close(process)
        assert (prefix.parent / "state.json").read_bytes() == identity
        assert ET.parse(config).find(".//GUIConfig[@name='ScintillaPrimaryView']").attrib["zoom"] == zoom
        from runtime.arm64ec import native_launch_script
        native_launch_script(bundle, [])  # Verify the immutable source prefix again.
        result = {"schemaVersion": "cage.arm64-container-functional-test/v0", "status": "passed",
                  "architecture": "aarch64", "windowsArchitecture": "x86_64", "kernelPageSize": os.sysconf("SC_PAGE_SIZE"),
                  "runtimeImage": graph["runnerRuntime"]["image"], "seedDigest": plan["seedDigest"],
                  "save": True, "relaunch": True, "sameStateGeneration": True, "settingsZoom": zoom,
                  "immutableSeedVerified": True, "savedContents": document.read_text(),
                  "host": gui.command("uname", "-srmo")}
        (EVIDENCE / "functional-test.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
    except BaseException:
        subprocess.run(["scrot", str(EVIDENCE / "failure.png")], check=False)
        subprocess.run(["podman", "stop", "--time", "3", "cage-arm-functional"], check=False, timeout=15)
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
        raise
    finally:
        for log in logs:
            log.close()


if __name__ == "__main__":
    main()
