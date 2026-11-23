#!/usr/bin/env python3
"""RC2 tests for orchestrator/watchdog.py (unchanged RC1 behaviour)."""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "orchestrator"))
import watchdog  # noqa: E402


class TestWatchdog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.beat = os.path.join(self.tmp.name, "heartbeat.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _write_beat(self, age_seconds):
        when = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        with open(self.beat, "w", encoding="utf-8") as f:
            json.dump({"project_id": "P-1",
                       "last_update": when.isoformat(),
                       "turn_number": 2, "status": "DISCUSSING"}, f)

    def test_fresh_is_ok(self):
        self._write_beat(60)
        result, code = watchdog.check(self.beat, 600)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(code, 0)

    def test_stale(self):
        self._write_beat(20 * 60)
        result, code = watchdog.check(self.beat, 600)
        self.assertEqual(result["status"], "stale")
        self.assertEqual(code, 1)

    def test_missing(self):
        result, code = watchdog.check(self.beat, 600)
        self.assertEqual(result["status"], "missing")
        self.assertEqual(code, 2)

    def test_corrupt(self):
        with open(self.beat, "w", encoding="utf-8") as f:
            f.write("{not json")
        result, code = watchdog.check(self.beat, 600)
        self.assertEqual(result["status"], "error")
        self.assertEqual(code, 2)

    def test_bad_timestamp(self):
        with open(self.beat, "w", encoding="utf-8") as f:
            json.dump({"project_id": "P-1", "last_update": "not-a-time"}, f)
        result, code = watchdog.check(self.beat, 600)
        self.assertEqual(result["status"], "error")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
