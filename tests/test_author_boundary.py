"""Fail-closed boundary regression; synthetic evidence is not live E2E proof."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

class TestAuthorBoundary(unittest.TestCase):
    def test_real_content_script_boundary_contract(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node unavailable")
        result = subprocess.run([node, str(Path(__file__).with_name("author_boundary_harness.js"))], capture_output=True, text=True, timeout=20)
        data = json.loads(result.stdout)
        self.assertEqual([c for c in data["checks"] if not c["pass"]], [])
        self.assertTrue(data["all_pass"])
        self.assertEqual(result.returncode, 0, result.stderr)
