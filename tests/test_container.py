"""Tests for the Cage Container Manager and runtime catalog."""
from __future__ import annotations
import unittest
from container.manager import (
    list_definitions,
    get_image_ref,
    get_local_image_ref,
    build_container,
)


class ContainerManagerTests(unittest.TestCase):

    def test_list_definitions_returns_all_providers(self):
        defs = list_definitions()
        names = [d["name"] for d in defs]
        self.assertIn("wine", names)
        self.assertIn("staging", names)
        self.assertNotIn("proton", names)
        self.assertIn("umu-proton-ge", names)
        self.assertNotIn("proton-ge", names)

    def test_get_image_ref_known_provider_returns_published_ref(self):
        self.assertEqual(get_image_ref("wine", "latest"),
                         "ghcr.io/myos-dev/cage-wine:11.0")
        self.assertEqual(get_image_ref("wine", "10.0"),
                         "ghcr.io/myos-dev/cage-wine:10.0")
        self.assertEqual(get_image_ref("staging", "latest"),
                         "ghcr.io/myos-dev/cage-wine-staging:11.10")
        self.assertEqual(get_image_ref("umu-proton-ge", "latest"),
                         "ghcr.io/myos-dev/cage-umu-proton-ge:GE-Proton11-1")

    def test_get_local_image_ref_known_provider(self):
        self.assertEqual(get_local_image_ref("wine", "latest"),
                         "cage/wine:11.0")
        self.assertEqual(get_local_image_ref("staging", "previous"),
                         "cage/wine-staging:11.9")

    def test_get_image_ref_unknown_falls_back_to_published_name(self):
        self.assertEqual(get_image_ref("unknown", "1.0"),
                         "ghcr.io/myos-dev/cage-unknown:1.0")
        self.assertEqual(get_local_image_ref("unknown", "1.0"),
                         "cage/unknown:1.0")

    def test_build_container_unknown_provider(self):
        result = build_container("nonexistent", "1.0")
        self.assertFalse(result.success)
        self.assertIn("Unknown provider/version", result.log)

    def test_build_container_no_docker(self):
        # Returns file-not-found or build-failed — not an exception
        result = build_container("wine", "latest", build_cmd="nonexistent-docker")
        self.assertFalse(result.success)
        self.assertIn("not found", result.log.lower())


class RuntimeCatalogTests(unittest.TestCase):

    def test_catalog_ci_matrix_contains_build_entries(self):
        from runtime.catalog import ci_matrix
        matrix = ci_matrix()
        self.assertIn("include", matrix)
        providers = {entry["provider"] for entry in matrix["include"]}
        self.assertEqual(providers, {"wine", "staging", "umu-proton-ge"})
        for entry in matrix["include"]:
            self.assertIn("dockerfile", entry)
            self.assertIn("build_arg", entry)
            self.assertIn("image_name", entry)
            self.assertIsInstance(entry["version"], str)

    def test_catalog_default_version_resolution(self):
        from runtime.catalog import resolve_catalog_version
        entry = resolve_catalog_version("wine", "default")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.version, "11.0")
        self.assertEqual(entry.requested_version, "default")
        self.assertEqual(entry.resolved_version, "11.0")
        self.assertEqual(entry.aliases, ("latest", "stable"))
        self.assertEqual(entry.package_version, "11.0.0.0~bookworm-1")
        self.assertEqual(entry.published_ref,
                         "ghcr.io/myos-dev/cage-wine:11.0")


    def test_latest_and_channel_aliases_resolve_to_pinned_versions(self):
        from runtime.catalog import resolve_catalog_version

        wine = resolve_catalog_version("wine", "latest")
        staging = resolve_catalog_version("staging", "previous")
        proton = resolve_catalog_version("umu-proton-ge", "latest")

        assert wine is not None
        assert staging is not None
        assert proton is not None
        self.assertEqual(wine.version, "11.0")
        self.assertEqual(wine.requested_version, "latest")
        self.assertEqual(wine.resolved_version, "11.0")
        self.assertEqual(wine.runner, "winehq-stable")
        self.assertEqual(wine.package_version, "11.0.0.0~bookworm-1")
        self.assertEqual(staging.version, "11.9")
        self.assertEqual(staging.package_version, "11.9~bookworm-1")
        self.assertEqual(proton.version, "GE-Proton11-1")
        self.assertEqual(proton.runner, "ge-proton")
        self.assertEqual(proton.launcher_version, "1.4.0")

    def test_catalog_ci_matrix_covers_curated_runner_versions_only(self):
        from runtime.catalog import ci_matrix

        versions = {(entry["provider"], entry["version"]) for entry in ci_matrix()["include"]}
        self.assertEqual(versions, {
            ("wine", "11.0"),
            ("wine", "10.0"),
            ("wine", "9.0"),
            ("staging", "11.10"),
            ("staging", "11.9"),
            ("staging", "11.0"),
            ("umu-proton-ge", "GE-Proton11-1"),
            ("umu-proton-ge", "GE-Proton10-34"),
            ("umu-proton-ge", "GE-Proton9-27"),
        })
        self.assertFalse(any(entry["version"] == "latest" for entry in ci_matrix()["include"]))

    def test_latest_tags_are_declared_as_publish_aliases_not_matrix_versions(self):
        from runtime.catalog import resolve_catalog_version

        wine = resolve_catalog_version("wine", "latest")
        proton = resolve_catalog_version("umu-proton-ge", "latest")
        assert wine is not None
        assert proton is not None
        self.assertIn("latest", wine.publish_tags)
        self.assertIn("latest", proton.publish_tags)
        self.assertEqual(wine.tag, "11.0")
        self.assertEqual(proton.tag, "GE-Proton11-1")


    def test_shell_build_list_includes_publish_alias_tags_for_bulk_builds(self):
        from runtime.catalog import shell_build_list

        rows = [line.split("\t") for line in shell_build_list().splitlines()]
        wine_latest = next(row for row in rows if row[0] == "wine" and row[1] == "11.0")
        self.assertGreaterEqual(len(wine_latest), 8)
        self.assertEqual(wine_latest[7], "latest stable")

    def test_valve_proton_and_legacy_proton_ge_are_not_active_providers(self):
        from runtime.catalog import resolve_catalog_version
        self.assertIsNone(resolve_catalog_version("proton", "default"))
        self.assertIsNone(resolve_catalog_version("proton-ge", "default"))


class RuntimeProviderOCITests(unittest.TestCase):

    def test_runtime_binding_includes_published_and_local_oci_images(self):
        from core.manifest import RuntimeSpec
        from runtime.providers import resolve_runtime
        binding = resolve_runtime(RuntimeSpec(
            provider="wine", version="latest",
        ))
        self.assertEqual(binding.version, "11.0")
        self.assertEqual(binding.requested_version, "latest")
        self.assertEqual(binding.resolved_version, "11.0")
        self.assertEqual(binding.runner, "winehq-stable")
        self.assertEqual(binding.package_version, "11.0.0.0~bookworm-1")
        self.assertEqual(binding.oci_image,
                         "ghcr.io/myos-dev/cage-wine:11.0")
        self.assertEqual(binding.local_oci_image,
                         "cage/wine:11.0")
        self.assertTrue(binding.runtime_usable)

    def test_runtime_binding_oci_image_staging(self):
        from core.manifest import RuntimeSpec
        from runtime.providers import resolve_runtime
        binding = resolve_runtime(RuntimeSpec(
            provider="staging", version="previous",
        ))
        self.assertEqual(binding.version, "11.9")
        self.assertEqual(binding.requested_version, "previous")
        self.assertEqual(binding.oci_image,
                         "ghcr.io/myos-dev/cage-wine-staging:11.9")
        self.assertEqual(binding.local_oci_image,
                         "cage/wine-staging:11.9")

    def test_runtime_binding_oci_image_umu_proton_ge(self):
        from core.manifest import RuntimeSpec
        from runtime.providers import resolve_runtime
        binding = resolve_runtime(RuntimeSpec(
            provider="umu-proton-ge", version="latest",
        ))
        self.assertEqual(binding.version, "GE-Proton11-1")
        self.assertEqual(binding.requested_version, "latest")
        self.assertEqual(binding.resolved_version, "GE-Proton11-1")
        self.assertEqual(binding.runner, "ge-proton")
        self.assertEqual(binding.launcher_version, "1.4.0")
        self.assertEqual(binding.oci_image,
                         "ghcr.io/myos-dev/cage-umu-proton-ge:GE-Proton11-1")
        self.assertEqual(binding.local_oci_image,
                         "cage/umu-proton-ge:GE-Proton11-1")
        self.assertEqual(binding.launcher, "umu")

    def test_oci_image_in_to_dict(self):
        from core.manifest import RuntimeSpec
        from runtime.providers import resolve_runtime
        binding = resolve_runtime(RuntimeSpec(
            provider="umu-proton-ge", version="latest",
        ))
        d = binding.to_dict()
        self.assertIn("ociImage", d)
        self.assertIn("localOciImage", d)
        self.assertEqual(d["ociImage"],
                         "ghcr.io/myos-dev/cage-umu-proton-ge:GE-Proton11-1")
        self.assertEqual(d["requestedVersion"], "latest")
        self.assertEqual(d["resolvedVersion"], "GE-Proton11-1")
        self.assertEqual(d["runner"], "ge-proton")
        self.assertEqual(d["launcherVersion"], "1.4.0")
        self.assertTrue(d["runtimeUsable"])

    def test_to_dict_omits_none_oci(self):
        """Custom providers without OCI mapping should omit the field."""
        from runtime.providers import register_provider, resolve_runtime
        from core.manifest import RuntimeSpec

        class CustomProvider:
            name = "custom-test"
            def resolve(self, spec):
                from runtime.providers import RuntimeBinding
                return RuntimeBinding(
                    spec.provider, spec.version, "wine",
                )

        register_provider(CustomProvider())
        binding = resolve_runtime(RuntimeSpec(
            provider="custom-test", version="1.0",
        ))
        d = binding.to_dict()
        self.assertIsNone(binding.oci_image)
        self.assertNotIn("ociImage", d)


if __name__ == "__main__":
    unittest.main()
