from __future__ import annotations

import unittest

from core.chocolatey.assets import load_asset


class PowerShell51CompilerContractTests(unittest.TestCase):
    def test_assembly_inventory_compiler_uses_explicit_framework_reference(self):
        script = load_asset("install-powershell51.sh")

        self.assertIn('framework_dir="$(dirname "$candidate")"', script)
        self.assertIn('mscorlib="$framework_dir/mscorlib.dll"', script)
        self.assertIn('mscorlib_win="$(winepath -w "$mscorlib")"', script)
        self.assertIn('/nologo /noconfig /nostdlib+ /target:exe', script)
        self.assertIn('"/reference:$mscorlib_win"', script)
        self.assertIn('assembly-inventory-compile.log', script)
        self.assertNotIn('wine "$csc_exe" /nologo /target:exe', script)


if __name__ == "__main__":
    unittest.main()
