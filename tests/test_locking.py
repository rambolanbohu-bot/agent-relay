#!/usr/bin/env python3
"""RC2 tests for orchestrator/locking.py (Security-1).

Proves: a second writer cannot take the lock while the first holds it
(it times out instead of deleting the first writer's lock file), the lock
file is never deleted, and the lock is released when the holder exits.
"""

import multiprocessing
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "orchestrator"))
from locking import FileLock  # noqa: E402


def _hold_lock(lock_path, hold_seconds, ready_queue):
    with FileLock(lock_path, timeout=10):
        ready_queue.put("locked")
        time.sleep(hold_seconds)


class TestFileLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lock = os.path.join(self.tmp.name, "test.lock")

    def tearDown(self):
        self.tmp.cleanup()

    def test_second_writer_times_out_instead_of_stealing(self):
        ctx = multiprocessing.get_context("spawn")
        ready = ctx.Queue()
        holder = ctx.Process(target=_hold_lock,
                             args=(self.lock, 3, ready))
        holder.start()
        try:
            self.assertEqual(ready.get(timeout=5), "locked")
            # The lock file exists and belongs to a LIVE holder. A second
            # writer must time out — never delete the live lock (RC1 bug).
            with self.assertRaises(TimeoutError):
                with FileLock(self.lock, timeout=1):
                    pass
            self.assertTrue(os.path.exists(self.lock),
                            "lock file was deleted while held")
        finally:
            holder.join(timeout=5)
        # After the holder exits, the lock is free again.
        with FileLock(self.lock, timeout=5):
            pass
        # The lock file is still on disk (never deleted by age).
        self.assertTrue(os.path.exists(self.lock))

    def test_reacquire_after_release(self):
        with FileLock(self.lock, timeout=5):
            pass
        with FileLock(self.lock, timeout=5):
            pass


if __name__ == "__main__":
    unittest.main()
