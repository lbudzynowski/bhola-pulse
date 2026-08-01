from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from src.bhola_cache import atomic_write_json, sanitize_process_name


class CacheTests(unittest.TestCase):
    def test_atomic_json_replaces_complete_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested/dashboard.json"
            atomic_write_json(output, {"sequence": 1})
            atomic_write_json(output, {"sequence": 2, "ok": True})
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), {"sequence": 2, "ok": True})
            self.assertEqual(list(output.parent.glob("*.tmp")), [])

    def test_process_name_removes_paths_whitespace_and_separators(self) -> None:
        value = sanitize_process_name("/private/location/worker name=local")
        self.assertEqual(value, "worker_name_local")
        for forbidden in ("/", "\\", " ", "="):
            self.assertNotIn(forbidden, value)

    def test_empty_process_name_is_unknown(self) -> None:
        self.assertEqual(sanitize_process_name(""), "unknown")
        self.assertEqual(sanitize_process_name(None), "unknown")


if __name__ == "__main__":
    unittest.main()
