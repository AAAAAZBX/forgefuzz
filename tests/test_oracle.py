from __future__ import annotations

import math
import struct
from pathlib import Path
import tempfile
import unittest

from fuzz.oracle import compare_float32_files, compare_values, load_float32


class OracleTests(unittest.TestCase):
    def test_exact_and_allclose(self):
        exact = compare_values([1.0], [1.00001], mode="exact", atol=1e-3, rtol=1e-3, equal_nan=True)
        close = compare_values([1.0], [1.00001], mode="allclose", atol=1e-3, rtol=0.0, equal_nan=True)
        self.assertFalse(exact["matches"])
        self.assertTrue(close["matches"])

    def test_nan_policy(self):
        self.assertTrue(compare_values([math.nan], [math.nan], mode="exact", atol=0, rtol=0, equal_nan=True)["matches"])
        self.assertFalse(compare_values([math.nan], [math.nan], mode="exact", atol=0, rtol=0, equal_nan=False)["matches"])
        self.assertTrue(compare_values([math.inf, -math.inf], [math.inf, -math.inf], mode="allclose", atol=0, rtol=0, equal_nan=True)["matches"])

    def test_binary_format_errors_and_compare(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            bad = root / "bad.bin"
            bad.write_bytes(b"abc")
            with self.assertRaises(ValueError):
                load_float32(bad)
            left, right = root / "left.bin", root / "right.bin"
            left.write_bytes(struct.pack("<2f", 1.0, 2.0))
            right.write_bytes(struct.pack("<2f", 1.0, 2.0))
            self.assertTrue(compare_float32_files(left, right, {"comparison": "exact", "atol": 0, "rtol": 0, "equal_nan": True})["matches"])


if __name__ == "__main__":
    unittest.main()
