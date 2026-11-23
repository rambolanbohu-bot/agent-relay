import json
import subprocess
import unittest
from pathlib import Path

class RC14RichEditor(unittest.TestCase):
    def test_native_editor_and_failure_paths(self):
        root=Path(__file__).resolve().parent.parent
        p=subprocess.run(["node",str(root/"tests/rc14_rich_editor_harness.js")],
            capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=30)
        self.assertEqual(p.returncode,0,p.stdout[-3000:]+" "+p.stderr[-3000:])
        obj=json.loads(p.stdout)
        self.assertTrue(obj["all_pass"])
        self.assertGreaterEqual(len(obj["checks"]),18)

if __name__ == "__main__":
    unittest.main()