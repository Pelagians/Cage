from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from artifact.bundle import create_bundle
from artifact.graph import build_execution_graph
from artifact.kube import create_kube_export_plan
from artifact.oci import create_oci_export_plan
from core.manifest import Manifest, ManifestError, load_manifest
from runtime.launcher import build_run_plan
from tests.bundle_fixtures import materialize_runnable_prefix

ROOT = Path(__file__).resolve().parents[1]
APP = {
    "schemaVersion": "cage.app/v0",
    "name": "selkies-demo",
    "version": "1.0.0",
    "runtime": {
        "provider": "wine",
        "version": "11.0",
        "network": "bridge",
        "wineGraphics": "xwayland",
    },
    "launch": {"entrypoint": "C:/Windows/notepad.exe"},
}


def _selkies_receipt(image: str, *, mode: str = "selkies") -> dict:
    return {
        "schemaVersion": "cage.oci-image-verification/v0",
        "success": True,
        "valid": True,
        "imageRef": image,
        "errors": [],
        "checks": [{"id": "graphics", "ok": True}],
        "artifactMetadata": {"imageGraphics": mode},
    }


class WineGraphicsContractTests(unittest.TestCase):
    def test_manifest_records_explicit_wine_graphics_mode(self):
        for mode in ("xwayland", "wayland"):
            with self.subTest(mode=mode):
                data = copy.deepcopy(APP)
                data["runtime"]["wineGraphics"] = mode
                manifest = Manifest.from_dict(data)
                self.assertEqual(manifest.runtime.wine_graphics, mode)
                self.assertEqual(manifest.to_dict()["runtime"]["wineGraphics"], mode)

    def test_manifest_rejects_unknown_wine_graphics_mode(self):
        data = copy.deepcopy(APP)
        data["runtime"]["wineGraphics"] = "automatic"
        with self.assertRaisesRegex(ManifestError, "runtime.wineGraphics"):
            Manifest.from_dict(data)

    def test_native_wayland_rejects_umu_until_proton_driver_is_proven(self):
        data = copy.deepcopy(APP)
        data["runtime"].update(
            {
                "provider": "umu-proton-ge",
                "version": "GE-Proton11-1",
                "wineGraphics": "wayland",
            }
        )
        with self.assertRaisesRegex(ManifestError, "native Wayland"):
            Manifest.from_dict(data)

    def test_graph_records_wayland_session_and_wine_driver(self):
        graph = build_execution_graph(Manifest.from_dict(APP))
        self.assertEqual(graph["graphics"]["supportedModes"], ["headless", "selkies"])
        self.assertEqual(graph["graphics"]["sessionBackend"], "wayland")
        self.assertEqual(graph["graphics"]["compositor"], "labwc")
        self.assertEqual(graph["graphics"]["wineGraphics"], "xwayland")


class SelkiesRunPlanTests(unittest.TestCase):
    def _bundle(self, tmp: str) -> Path:
        return create_bundle(Manifest.from_dict(APP), Path(tmp), dry_run=True)

    def test_selkies_plan_publishes_only_https_and_inherits_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = build_run_plan(
                self._bundle(tmp),
                graphics="selkies",
                engine="docker",
                network="bridge",
                selkies_port=3443,
                allow_non_runnable=True,
            )
        argv = plan["container"]["argv"]
        self.assertIn("127.0.0.1:3443:3001", argv)
        self.assertNotIn("5900", " ".join(argv))
        self.assertNotIn("6080", " ".join(argv))
        self.assertEqual(argv[-1], plan["runtime"]["image"])
        self.assertEqual(plan["graphics"]["httpsPort"], 3443)
        self.assertEqual(plan["graphics"]["wineGraphics"], "xwayland")
        self.assertEqual(
            plan["container"]["environment"]["CAGE_SESSION_MODE"], "selkies"
        )
        self.assertEqual(
            plan["container"]["environment"]["CAGE_WINE_GRAPHICS"], "xwayland"
        )

    def test_native_wayland_rejects_headless_run_and_export(self):
        data = copy.deepcopy(APP)
        data["runtime"]["wineGraphics"] = "wayland"
        data["runtime"]["network"] = "bridge"
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(data), Path(tmp), dry_run=True)
            materialize_runnable_prefix(bundle, entrypoint=APP["launch"]["entrypoint"])
            with self.assertRaisesRegex(Exception, "requires graphics selkies"):
                build_run_plan(
                    bundle,
                    graphics="headless",
                    engine="docker",
                    allow_non_runnable=True,
                )
            with self.assertRaisesRegex(Exception, "requires graphics selkies"):
                create_oci_export_plan(
                    bundle, tag="cage-demo:headless", graphics="headless"
                )

    def test_selkies_port_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            for port in (0, 1.5, 65536, True):
                with (
                    self.subTest(port=port),
                    self.assertRaisesRegex(Exception, "between 1 and 65535"),
                ):
                    build_run_plan(
                        bundle,
                        graphics="selkies",
                        network="bridge",
                        selkies_port=port,
                        engine="docker",
                        allow_non_runnable=True,
                    )

    def test_selkies_requires_bridge_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            with self.assertRaisesRegex(
                Exception, "graphics selkies requires network bridge"
            ):
                build_run_plan(
                    bundle,
                    graphics="selkies",
                    engine="docker",
                    network="none",
                    allow_non_runnable=True,
                )


class ProducerRuntimeQualificationTests(unittest.TestCase):
    def test_future_cfw_release_can_declare_selkies_session_contract(self):
        import yaml

        data = yaml.safe_load(
            (ROOT / "recipes/notepadplusplus.cage.yaml").read_text(encoding="utf-8")
        )
        artifact = json.loads(
            (
                ROOT / "core/chocolatey/assets/cfw-runtime-v1.0.3-wine-11.0.json"
            ).read_text(encoding="utf-8")
        )
        artifact["sessionContract"] = "cage.selkies-wayland/v1"
        artifact["selkiesImage"] = (
            "ghcr.io/pelagians/cage-wine-selkies@sha256:" + "e" * 64
        )
        data["modules"][0]["install"]["runtimeArtifact"] = artifact
        graph = build_execution_graph(Manifest.from_dict(data))
        self.assertEqual(
            graph["runnerRuntime"]["sessionContract"], "cage.selkies-wayland/v1"
        )

    def test_cfw_desktop_qualification_fields_are_both_or_neither(self):
        import yaml

        data = yaml.safe_load(
            (ROOT / "recipes/notepadplusplus.cage.yaml").read_text(encoding="utf-8")
        )
        artifact = json.loads(
            (
                ROOT / "core/chocolatey/assets/cfw-runtime-v1.0.3-wine-11.0.json"
            ).read_text(encoding="utf-8")
        )
        artifact["selkiesImage"] = (
            "ghcr.io/pelagians/cage-wine-selkies@sha256:" + "e" * 64
        )
        data["modules"][0]["install"]["runtimeArtifact"] = artifact
        with self.assertRaisesRegex(ManifestError, "must be declared together"):
            Manifest.from_dict(data)

    def test_unqualified_cfw_runtime_fails_closed_before_launch(self):
        manifest = load_manifest(ROOT / "recipes/notepadplusplus.cage.yaml")
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(manifest, Path(tmp), dry_run=True)
            with self.assertRaisesRegex(Exception, "not qualified"):
                build_run_plan(
                    bundle,
                    graphics="selkies",
                    engine="docker",
                    allow_non_runnable=True,
                )


class SelkiesImageContractTests(unittest.TestCase):
    def test_all_runtime_images_inherit_digest_pinned_selkies_and_s6(self):
        for rel in (
            "container/desktop/wine/Dockerfile",
            "container/desktop/wine-staging/Dockerfile",
        ):
            with self.subTest(rel=rel):
                text = (ROOT / rel).read_text(encoding="utf-8")
                self.assertRegex(
                    text,
                    r"ARG SELKIES_BASE_IMAGE=ghcr\.io/linuxserver/baseimage-selkies:[^\s]+@sha256:[0-9a-f]{64}",
                )
                self.assertIn("FROM ${SELKIES_BASE_IMAGE}", text)
                self.assertNotIn("Winetricks/winetricks/master", text)
                self.assertRegex(text, r"ARG WINETRICKS_COMMIT=[0-9a-f]{40}")
                self.assertRegex(text, r"ARG WINETRICKS_SHA256=[0-9a-f]{64}")
                self.assertIn("COPY container/selkies/root/ /", text)
                self.assertIn("EXPOSE 3001", text)
                self.assertNotIn("ENTRYPOINT", text)
                for obsolete in ("xvfb", "x11vnc", "novnc", "websockify"):
                    self.assertNotIn(obsolete, text.lower())

    def test_selkies_overlay_defines_labwc_and_s6_startup(self):
        autostart = ROOT / "container/selkies/root/defaults/autostart_wayland"
        init = ROOT / "container/selkies/root/custom-cont-init.d/10-cage-session"
        labwc = ROOT / "container/selkies/root/defaults/labwc.xml"
        self.assertTrue(autostart.is_file())
        self.assertTrue(init.is_file())
        self.assertTrue(labwc.is_file())
        selector = (
            ROOT / "container/selkies/root/usr/local/libexec/cage-select-wine-graphics"
        )
        self.assertTrue(selector.is_file())
        self.assertIn("Software\\Wine\\Drivers", selector.read_text(encoding="utf-8"))
        self.assertIn("Graphics", selector.read_text(encoding="utf-8"))
        self.assertIn("CAGE_LAUNCH_SCRIPT_B64", autostart.read_text(encoding="utf-8"))


class SelkiesOCIContractTests(unittest.TestCase):
    def test_application_image_inherits_s6_entrypoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(APP), Path(tmp), dry_run=True)
            materialize_runnable_prefix(bundle, entrypoint=APP["launch"]["entrypoint"])
            plan = create_oci_export_plan(bundle, tag="cage-demo:1", graphics="selkies")
        content = plan["containerfile"]["content"]
        self.assertNotIn("ENTRYPOINT", content)
        self.assertIn("FROM ghcr.io/pelagians/cage-wine-selkies:11.0", content)
        self.assertIn("CAGE_APP_LAUNCHER=/usr/local/bin/cage-app-launch", content)
        self.assertIn("CAGE_SESSION_MODE=selkies", content)


class SelkiesKubernetesContractTests(unittest.TestCase):
    def test_headless_export_does_not_inherit_selkies_root_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(APP), Path(tmp), dry_run=True)
            plan = create_kube_export_plan(
                bundle,
                image="ghcr.io/pelagians/cage-app@sha256:" + "a" * 64,
                graphics="headless",
            )
        deployment = next(
            item for item in plan["resources"] if item["kind"] == "Deployment"
        )
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        self.assertNotIn("command", container)
        self.assertNotIn("securityContext", container)
        self.assertFalse(
            any(
                v["name"] == "cage-config"
                for v in deployment["spec"]["template"]["spec"]["volumes"]
            )
        )

    def test_selkies_export_rejects_unverified_wrong_mode_and_multiple_replicas(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(APP), Path(tmp), dry_run=True)
            image = "ghcr.io/acme/cage-app@sha256:" + "a" * 64
            with self.assertRaisesRegex(Exception, "verify receipt"):
                create_kube_export_plan(bundle, image=image, graphics="selkies")
            with self.assertRaisesRegex(Exception, "incomplete or failed"):
                create_kube_export_plan(
                    bundle,
                    image=image,
                    graphics="selkies",
                    image_verification={
                        "valid": True,
                        "imageRef": image,
                        "artifactMetadata": {"imageGraphics": "selkies"},
                    },
                )
            with self.assertRaisesRegex(Exception, "not a Selkies"):
                create_kube_export_plan(
                    bundle,
                    image=image,
                    graphics="selkies",
                    image_verification=_selkies_receipt(image, mode="headless"),
                )
            with self.assertRaisesRegex(Exception, "exactly one replica"):
                create_kube_export_plan(
                    bundle,
                    image=image,
                    graphics="selkies",
                    replicas=2,
                    image_verification=_selkies_receipt(image, mode="selkies"),
                )

    def test_selkies_export_adds_https_service_and_minimum_init_capabilities(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(APP), Path(tmp), dry_run=True)
            image = "ghcr.io/acme/cage-app@sha256:" + "a" * 64
            plan = create_kube_export_plan(
                bundle,
                image=image,
                graphics="selkies",
                image_verification=_selkies_receipt(image, mode="selkies"),
            )
        service = next(r for r in plan["resources"] if r["kind"] == "Service")
        ingress = next(
            r
            for r in plan["resources"]
            if r["kind"] == "NetworkPolicy"
            and r["metadata"]["name"].endswith("deny-ingress")
        )
        self.assertEqual(ingress["spec"]["ingress"], [])
        deployment = next(r for r in plan["resources"] if r["kind"] == "Deployment")
        self.assertEqual(
            service["spec"]["ports"],
            [{"name": "https", "port": 3001, "targetPort": 3001}],
        )
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(
            container["ports"],
            [{"name": "https", "containerPort": 3001, "protocol": "TCP"}],
        )
        security = container["securityContext"]
        self.assertFalse(security["allowPrivilegeEscalation"])
        self.assertFalse(security["privileged"])
        self.assertEqual(
            security["capabilities"],
            {"drop": ["ALL"], "add": ["CHOWN", "SETGID", "SETUID"]},
        )
        self.assertEqual(container["command"], ["/init"])


if __name__ == "__main__":
    unittest.main()
