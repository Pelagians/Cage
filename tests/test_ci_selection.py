import unittest

from runtime.catalog import ci_matrix
from runtime.ci_selection import select


class MatrixSelectionTests(unittest.TestCase):
    def setUp(self):
        self.rows = ci_matrix()["include"]

    def test_wine_dockerfile_selects_both_channels(self):
        selected = select(self.rows, ["container/runtimes/wine/Dockerfile"])
        self.assertEqual(len(selected), 6)
        self.assertEqual({r["provider"] for r in selected}, {"wine", "staging"})

    def test_proton_dockerfile_selects_only_proton(self):
        selected = select(self.rows, ["container/runtimes/umu-proton-ge/Dockerfile"])
        self.assertEqual(len(selected), 3)
        self.assertEqual({r["provider"] for r in selected}, {"umu-proton-ge"})

    def test_shared_or_unknown_change_selects_full_matrix(self):
        self.assertEqual(select(self.rows, ["container/selkies/root/foo"]), self.rows)
        self.assertEqual(select(self.rows, ["runtime/catalog.json"]), self.rows)


if __name__ == "__main__":
    unittest.main()
