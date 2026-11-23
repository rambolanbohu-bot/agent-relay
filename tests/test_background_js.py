#!/usr/bin/env python3
"""RC4-hotfix4 tests for transport/extension/background.js (HOTFIX 4
P2-C + GATE-SEAMLESS-CONTINUITY).

Runs the Node harness (tests/background_js_harness.js), which loads
the REAL background.js with stubbed chrome globals and checks the
session-binding contract:
- the first host command for a site binds the first tab of the
  query, and the result carries tab_id + tab_rebound:true;
- a later host command for the same site reuses the BOUND tab even
  when a fresh query would return a different tab first
  (tab_rebound:false) — taking tabs[0] from every query would send
  the next round to the WRONG session when several tabs of the same
  site are open;
- when the bound tab is gone, the next command re-binds to a live
  tab (tab_rebound:true);
- a content-script message binds its sender tab for the site;
- an explicit tab_id in a host command wins over the stored binding
  and becomes the new binding;
- an explicit session_id binds independently per session;
- the muse site binds independently from the chatgpt site;
- no tab for the site returns no_tab_for_site.

Skipped if node is not available. The harness simulates the
extension host, so it proves the background script's own routing
logic — not real Chrome. Real-Chrome end-to-end testing is still
PENDING (see docs/KNOWN-LIMITATIONS.md).
"""

import json
import os
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


class TestBackgroundJs(unittest.TestCase):
    def test_harness_all_checks_pass(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available for background.js harness")
        proc = subprocess.run(
            [node, os.path.join(HERE, "background_js_harness.js")],
            capture_output=True, text=True, timeout=60)
        try:
            result = json.loads(proc.stdout)
        except ValueError:
            self.fail(
                f"harness did not print JSON: stdout={proc.stdout!r} "
                f"stderr={proc.stderr!r}")
        failed = [c for c in result.get("checks", [])
                  if not c.get("pass")]
        self.assertEqual(failed, [],
                         f"failing harness checks: {failed}")
        self.assertTrue(result.get("all_pass"), result)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
