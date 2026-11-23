#!/usr/bin/env python3
"""RC4-hotfix6 tests: adapter collect_dom + diagnostics passthrough
(tests/test_adapter_collect_dom.py).

HOTFIX 6 (B2/B3/B4, ROUND 25):
- collect_dom() is the adapter side of the optional read-only
  de-sensitized DOM collector (content.js doCollectDom). It sends
  a collect_dom command with the two known test markers and
  returns the de-sensitized JSON (found flags, role-selector
  counts, node structures) with no message content. The key
  diagnostic (user_found=true with role_selector_counts.user=0)
  must survive the round trip intact.
- read_latest() passes the diagnostic inventory through on
  not_found and the recognition strategy through on found.
- send() passes the diagnostic inventory, the button time series
  and the tab visibility state through on uncertain and not_sent
  results (the ok path already returns the full envelope as
  "detail").

These tests patch _wait_outbox to return a canned outbox record
(the file reading itself is covered by
tests/test_adapter_late_receipt.py) and assert the response
handling. They run on Linux with no native host process.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)

sys.path.insert(0, os.path.join(PKG, "transport"))
sys.path.insert(0, os.path.join(PKG, "orchestrator"))
from adapter import Adapter  # noqa: E402


def _record(nonce, **envelope):
    env = {"type": "collect_dom_result",
           "origin": "https://chatgpt.com", "nonce": nonce}
    env.update(envelope)
    return {"direction": "extension_to_coordinator", "envelope": env}


class AdapterCollectDomTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.skill_root = os.path.join(self.tmp.name, "skill")
        self.nh_dir = os.path.join(
            self.skill_root, "orchestrator", "state", "native_host")
        os.makedirs(self.nh_dir, exist_ok=True)
        # A fresh heartbeat so native_host_connected() is True.
        with open(os.path.join(self.nh_dir, "heartbeat.json"),
                  "w", encoding="utf-8") as f:
            json.dump({"last_update": datetime.now(timezone.utc)
                       .isoformat()}, f)
        self.adapter = Adapter(self.skill_root, mode="native_host")
        self.commands = []
        self.adapter._write_command = self.commands.append
        self._rec = None

    def tearDown(self):
        self.tmp.cleanup()

    def _answer(self, rec):
        """Make _wait_outbox return this record (or None)."""
        self._rec = rec
        self.adapter._wait_outbox = (
            lambda nonce, timeout: self._rec)


class TestCollectDom(AdapterCollectDomTestBase):
    def test_collect_dom_returns_desensitized_json(self):
        detail = {
            "user_found": True, "assistant_found": True,
            "role_selector_counts": {"user": 1, "assistant": 1},
            "user_structure": [{"level": 0, "tag": "div",
                                "authorRole": "user"}],
            "assistant_structure": [{"level": 0, "tag": "div",
                                     "authorRole": "assistant"}],
        }
        self._answer(_record("n-collect-1", ok=True, **detail))
        out = self.adapter.collect_dom(
            "chatgpt", "H5-B2-20261120-01", "ACK-H5-B2-20261120-01",
            project_id="p1")
        self.assertTrue(out["ok"])
        self.assertEqual(out["detail"]["user_found"], True)
        self.assertEqual(out["detail"]["role_selector_counts"],
                         {"user": 1, "assistant": 1})
        # The command carried the markers and the type.
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(self.commands[0]["type"], "collect_dom")
        self.assertEqual(self.commands[0]["user_marker"],
                         "H5-B2-20261120-01")
        self.assertEqual(self.commands[0]["assistant_marker"],
                         "ACK-H5-B2-20261120-01")

    def test_collect_dom_key_diagnostic_survives(self):
        # user_found=true with role_selector_counts.user=0 is the
        # direct evidence the user role selector is broken (ROUND
        # 25). It must not be normalised away.
        detail = {
            "user_found": True, "assistant_found": True,
            "role_selector_counts": {"user": 0, "assistant": 1},
            "user_structure": [{"level": 0, "tag": "article",
                                "authorRole": None}],
            "assistant_structure": [],
        }
        self._answer(_record("n-collect-2", ok=True, **detail))
        out = self.adapter.collect_dom(
            "chatgpt", "H5-B2-20261120-01", "ACK-H5-B2-20261120-01")
        self.assertTrue(out["ok"])
        self.assertTrue(out["detail"]["user_found"])
        self.assertEqual(out["detail"]["role_selector_counts"]["user"],
                         0)

    def test_collect_dom_timeout(self):
        self._answer(None)
        out = self.adapter.collect_dom(
            "chatgpt", "H5-B2-20261120-01", "ACK-H5-B2-20261120-01")
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "timeout")

    def test_collect_dom_extension_error(self):
        self._answer(_record("n-collect-3", ok=False,
                             error="missing_marker"))
        out = self.adapter.collect_dom("chatgpt", "", "")
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "missing_marker")

    def test_collect_dom_no_host_returns_handoff(self):
        adapter = Adapter(self.skill_root, mode="browser_task")
        out = adapter.collect_dom("chatgpt", "u", "a")
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "native_host_not_connected")
        self.assertIn("handoff", out)


class TestDiagnosticsPassthrough(AdapterCollectDomTestBase):
    def test_read_latest_not_found_passes_diagnostics(self):
        diag = {"kind": "assistant", "turn_count": 3,
                "strategies_tried": ["role_attribute",
                                     "after_user_turn"],
                "inventory": [{"tag": "ARTICLE", "role": None,
                               "text_len": 12}]}
        self._answer(_record("n-read-1", type="read_result",
                             found=False, diagnostics=diag))
        out = self.adapter.read_latest("chatgpt")
        self.assertTrue(out["ok"])
        self.assertFalse(out["found"])
        self.assertEqual(out["diagnostics"], diag)

    def test_read_latest_found_passes_strategy(self):
        import hashlib
        content = "assistant reply here"
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self._answer(_record(
            "n-read-2", type="read_result", found=True,
            content=content, content_sha256=digest, streaming=False,
            strategy="after_user_turn"))
        out = self.adapter.read_latest("chatgpt")
        self.assertTrue(out["found"])
        self.assertEqual(out["content"], content)
        self.assertEqual(out["strategy"], "after_user_turn")

    def test_send_uncertain_passes_diagnostics_and_timeline(self):
        diag = {"kind": "user", "turn_count": 1,
                "strategies_tried": ["role_attribute", "text_anchor"],
                "inventory": []}
        timeline = [
            {"t_ms": 0, "label": "before_input",
             "visibility": "hidden",
             "button": {"exists": False, "disabled": None}},
            {"t_ms": 10000, "label": "timeout",
             "visibility": "hidden",
             "button": {"exists": False, "disabled": None}},
        ]
        self._answer(_record(
            "n-send-1", type="send_result", ok=False,
            delivery="uncertain", error="send_unconfirmed",
            diagnostics=diag, button_timeline=timeline,
            visibility_state="hidden"))
        out = self.adapter.send("chatgpt", "hello", nonce="n-send-1")
        self.assertFalse(out["ok"])
        self.assertTrue(out["uncertain"])
        self.assertEqual(out["delivery"], "uncertain")
        self.assertEqual(out["diagnostics"], diag)
        self.assertEqual(out["button_timeline"], timeline)
        self.assertEqual(out["visibility_state"], "hidden")

    def test_send_not_sent_passes_timeline_and_visibility(self):
        timeline = [
            {"t_ms": 0, "label": "before_input",
             "visibility": "hidden",
             "button": {"exists": False, "disabled": None}},
            {"t_ms": 10000, "label": "timeout",
             "visibility": "hidden",
             "button": {"exists": False, "disabled": None}},
        ]
        self._answer(_record(
            "n-send-2", type="send_result", ok=False,
            delivery="not_sent",
            error="send_button_missing_after_input",
            button_timeline=timeline, visibility_state="hidden"))
        out = self.adapter.send("chatgpt", "hello", nonce="n-send-2")
        self.assertFalse(out["ok"])
        self.assertEqual(out["delivery"], "not_sent")
        self.assertEqual(out["error"],
                         "send_button_missing_after_input")
        self.assertEqual(out["button_timeline"], timeline)
        self.assertEqual(out["visibility_state"], "hidden")


if __name__ == "__main__":
    unittest.main()
