"""Tests for the WinForge Container Manager."""
from __future__ import annotations
import unittest
from container.manager import (
    list_definitions,
    get_image_ref,
    build_container,
)


class ContainerManagerTests(unittest.TestCase):

    def test_list_definitions_returns_all_providers(self):
        defs = list_definitions()
        names = [d["name"] for d in defs]
        self.assertIn("wine", names)
        self.assertIn("staging", names)
        self.assertIn("proton", names)
        self.assertIn("proton-ge", names)

    def test_get_image_ref_known_provider(self):
        self.assertEqual(get_image_ref("wine", "9.0"), "winforge/wine:9.0")
        self.assertEqual(get_image_ref("staging", "9.0"),
                         "winforge/wine-staging:9.0")
        self.assertEqual(get_image_ref("proton", "9.0"),
                         "winforge/proton:9.0")
        self.assertEqual(get_image_ref("proton-ge", "GE-Proton9-27"),
                         "winforge/proton-ge:GE-Proton9-27")

    def test_get_image_ref_unknown_falls_back(self):
        self.assertEqual(get_image_ref("unknown", "1.0"),
                         "winforge/unknown:1.0")

    def test_build_container_unknown_provider(self):
        result = build_container("nonexistent", "1.0")
        self.assertFalse(result.success)
        self.assertIn("Unknown provider", result.log)

    def test_build_container_no_docker(self):
        # Returns file-not-found or build-failed — not an exception
        result = build_container("wine", "9.0", build_cmd="nonexistent-docker")
        self.assertFalse(result.success)
        self.assertIn("not found", result.log.lower())


class RuntimeProviderOCITests(unittest.TestCase):

    def test_runtime_binding_includes_oci_image(self):
        from core.manifest import RuntimeSpec
        from runtime.providers import resolve_runtime
        binding = resolve_runtime(RuntimeSpec(
            provider="wine", version="9.0",
        ))
        self.assertIsNotNone(binding.oci_image)
        self.assertEqual(binding.oci_image, "winforge/wine:9.0")

    def test_runtime_binding_oci_image_staging(self):
        from core.manifest import RuntimeSpec
        from runtime.providers import resolve_runtime
        binding = resolve_runtime(RuntimeSpec(
            provider="staging", version="9.0",
        ))
        self.assertEqual(binding.oci_image, "winforge/wine-staging:9.0")

    def test_runtime_binding_oci_image_proton_ge(self):
        from core.manifest import RuntimeSpec
        from runtime.providers import resolve_runtime
        binding = resolve_runtime(RuntimeSpec(
            provider="proton-ge", version="GE-Proton9-27",
        ))
        self.assertEqual(binding.oci_image,
                         "winforge/proton-ge:GE-Proton9-27")

    def test_oci_image_in_to_dict(self):
        from core.manifest import RuntimeSpec
        from runtime.providers import resolve_runtime
        binding = resolve_runtime(RuntimeSpec(
            provider="proton", version="9.0",
        ))
        d = binding.to_dict()
        self.assertIn("ociImage", d)
        self.assertEqual(d["ociImage"], "winforge/proton:9.0")

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
