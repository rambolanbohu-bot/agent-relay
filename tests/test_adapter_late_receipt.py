#!/usr/bin/env python3
"""RC4-hotfix5 P2 tests: adapter late-receipt reconciliation
(tests/test_adapter_late_receipt.py).

ATTEMPT-08 (2026-11-20): B2 still failed on the real page. The
test text stayed in the composer, the Adapter timed out, and the
send_result sat in the queue as send_unconfirmed. Two adapter
defects contributed:

1. _wait_outbox() read the outbox WITHOUT the FileLock while the
   native host writes under it, and counted every line it looked
   at as "seen" — a record read mid-write was lost forever, never
   re-examined once complete. A send receipt could therefore
   arrive and be dropped, leaving the transaction UNCERTAIN even
   though the delivery evidence was sitting in the outbox.
2. A receipt that arrived AFTER send()'s timeout was dropped
   instead of reconciled: send() returned timeout/UNCERTAIN and
   nothing ever re-read the outbox for that nonce.

Hotfix5 fixes both: _wait_outbox() counts only COMPLETE lines
(terminated by "\\n") as seen, so a partial line is re-read on
the next poll; send() does one final _find_outbox_record() scan
after a timeout; and the new reconcile_send() upgrades an
UNCERTAIN transaction to delivered-late ONLY when the late
receipt proves delivery (ok:true + delivery "message_sent" + a
non-null message_id from a positively-identified new user node).
A reply_started-only receipt (no message_id) or an uncertain
receipt does NOT upgrade. NEVER auto-resend on UNCERTAIN.

These tests drive send() / reconcile_send() through
transport/adapter.py against the real native host, with this
test playing the extension side — including a late-answering
extension (send_delay) that replies only after send() timed out.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)

sys.path.insert(0, os.path.join(PKG, "transport"))
sys.path.insert(0, os.path.join(PKG, "orchestrator"))
sys.path.insert(0, HERE)
from adapter import Adapter  # noqa: E402
from test_native_host import read_msg, write_msg  # noqa: E402
import file_log  # noqa: E402

HOST = os.path.join(PKG, "transport", "native_host.py")


def _outbox_record(nonce, **envelope):
    """One outbox record in the shape the native host writes:
    {"direction": ..., "envelope": {...}}."""
    env = {"type": "send_result", "origin": "https://chatgpt.com",
           "nonce": nonce}
    env.update(envelope)
    return {"direction": "extension_to_coordinator", "envelope": env}


class TestAdapterLateReceipt(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.skill_root = os.path.join(self.tmp.name, "skill")
        self.nh_dir = os.path.join(
            self.skill_root, "orchestrator", "state", "native_host")
        os.makedirs(self.nh_dir, exist_ok=True)
        self.outbox = os.path.join(self.nh_dir, "outbox.jsonl")
        self.adapter = Adapter(self.skill_root, mode="native_host")
        self.proc = None
        self._stop = threading.Event()
        self._thread = None
        # Extension behaviour: "confirmed" (with message_id),
        # "confirmed_no_id" (reply_started only, no message_id),
        # "uncertain", "not_sent". send_delay seconds before the
        # extension answers a send command.
        self.send_mode = "confirmed"
        self.send_delay = 0

    def tearDown(self):
        self._stop.set()
        if self.proc is not None:
            try:
                self.proc.stdin.close()
            except (BrokenPipeError, ValueError):
                pass
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
            for stream in (self.proc.stdout, self.proc.stderr):
                try:
                    stream.close()
                except (ValueError, OSError):
                    pass
        self.tmp.cleanup()

    def _start_host(self, with_extension=True):
        self.proc = subprocess.Popen(
            [sys.executable, HOST, "--state-dir", self.nh_dir],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        deadline = time.time() + 10
        while time.time() < deadline:
            if (os.path.exists(os.path.join(self.nh_dir, "secret"))
                    and os.path.exists(
                        os.path.join(self.nh_dir, "heartbeat.json"))):
                break
            time.sleep(0.1)
        self.assertTrue(
            os.path.exists(os.path.join(self.nh_dir, "secret")),
            "native host did not start / create its secret")
        self.assertTrue(self.adapter.native_host_connected(),
                        "native host heartbeat is not fresh")
        if with_extension:
            self._thread = threading.Thread(target=self._extension_loop,
                                            daemon=True)
            self._thread.start()

    def _extension_loop(self):
        while not self._stop.is_set():
            try:
                msg = read_msg(self.proc, timeout=2)
            except Exception:
                return
            if msg is None:
                return
            if not isinstance(msg, dict):
                continue
            nonce = msg.get("nonce")
            mtype = msg.get("type")
            try:
                if mtype == "send":
                    if self.send_delay:
                        time.sleep(self.send_delay)
                    if self.send_mode == "uncertain":
                        write_msg(self.proc, {
                            "type": "send_result",
                            "origin": "https://chatgpt.com",
                            "nonce": nonce, "ok": False,
                            "delivery": "uncertain",
                            "error": "send_unconfirmed"})
                    elif self.send_mode == "not_sent":
                        write_msg(self.proc, {
                            "type": "send_result",
                            "origin": "https://chatgpt.com",
                            "nonce": nonce, "ok": False,
                            "delivery": "not_sent",
                            "error": "send_button_never_enabled"})
                    elif self.send_mode == "confirmed_no_id":
                        write_msg(self.proc, {
                            "type": "send_result",
                            "origin": "https://chatgpt.com",
                            "nonce": nonce, "ok": True,
                            "delivery": "message_sent",
                            "confirmation": "reply_started"})
                    else:  # confirmed, with a positively-identified node
                        write_msg(self.proc, {
                            "type": "send_result",
                            "origin": "https://chatgpt.com",
                            "nonce": nonce, "ok": True,
                            "delivery": "message_sent",
                            "message_id": "msg-late-1",
                            "confirmation": "new_user_node"})
                elif mtype == "ping":
                    write_msg(self.proc, {
                        "type": "pong",
                        "origin": "https://chatgpt.com",
                        "nonce": nonce})
            except (BrokenPipeError, ValueError, OSError):
                return

    def _write_outbox(self, rec):
        with open(self.outbox, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    # -- _find_outbox_record / complete-line reading ------------------------

    def test_find_outbox_record_finds_receipt(self):
        nonce = "n-find-1"
        self._write_outbox(_outbox_record(nonce, ok=True,
                                          delivery="message_sent",
                                          message_id="msg-find-1"))
        rec = self.adapter._find_outbox_record(nonce)
        self.assertIsNotNone(rec, "_find_outbox_record missed a receipt")
        self.assertEqual(rec["envelope"]["nonce"], nonce)
        self.assertEqual(rec["envelope"]["message_id"], "msg-find-1")

    def test_find_outbox_record_returns_last_match(self):
        nonce = "n-find-2"
        self._write_outbox(_outbox_record(nonce, ok=False,
                                          delivery="uncertain",
                                          error="send_unconfirmed"))
        self._write_outbox(_outbox_record(nonce, ok=True,
                                          delivery="message_sent",
                                          message_id="msg-find-2"))
        rec = self.adapter._find_outbox_record(nonce)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["envelope"]["delivery"], "message_sent")

    def test_partial_line_is_not_counted_as_seen(self):
        # HOTFIX 5 P2 defect 1: a record read mid-write (no trailing
        # newline yet) must NOT be counted as seen and lost. Write
        # a partial line, confirm _wait_outbox does not match it,
        # then complete the line and confirm _find_outbox_record
        # finds it.
        nonce = "n-partial-1"
        rec = _outbox_record(nonce, ok=True, delivery="message_sent",
                             message_id="msg-partial-1")
        line = json.dumps(rec)
        with open(self.outbox, "a", encoding="utf-8") as f:
            f.write(line)  # NO trailing newline: mid-write
        self.assertIsNone(
            self.adapter._wait_outbox(nonce, timeout=1),
            "a partial (mid-write) line matched the waiter")
        self.assertIsNone(
            self.adapter._find_outbox_record(nonce),
            "a partial (mid-write) line was returned as a record")
        with open(self.outbox, "a", encoding="utf-8") as f:
            f.write("\n")  # the writer finishes the line
        found = self.adapter._find_outbox_record(nonce)
        self.assertIsNotNone(
            found, "the completed line was not found after the "
                   "partial read (the pre-Hotfix5 race lost it)")
        self.assertEqual(found["envelope"]["message_id"], "msg-partial-1")

    # -- send() final scan after a timeout ----------------------------------

    def test_send_final_scan_delivers_late(self):
        # The receipt is already in the outbox, but _wait_outbox
        # missed it (simulated here by forcing it to return None,
        # as the pre-Hotfix5 mid-write race would). send() must do
        # one final scan and report delivered-late, not timeout.
        self._start_host(with_extension=False)
        nonce = "n-late-scan-1"
        self._write_outbox(_outbox_record(nonce, ok=True,
                                          delivery="message_sent",
                                          message_id="msg-late-scan-1"))
        orig_wait = self.adapter._wait_outbox
        self.adapter._wait_outbox = lambda n, t: None
        try:
            res = self.adapter.send("chatgpt", "late scan test",
                                    project_id="P-LATE-SCAN",
                                    nonce=nonce, timeout=1)
        finally:
            self.adapter._wait_outbox = orig_wait
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(res.get("delivery"), "message_sent")
        self.assertTrue(res.get("late"), res)
        self.assertEqual(res.get("message_id"), "m-" + nonce)

    def test_send_late_receipt_without_message_id_stays_uncertain(self):
        # A late receipt that proves the AI replied but carries no
        # message_id (reply_started only) does NOT prove THIS
        # message was delivered. It stays UNCERTAIN with the
        # evidence attached — never upgraded on a guess.
        self._start_host(with_extension=False)
        nonce = "n-late-scan-2"
        self._write_outbox(_outbox_record(nonce, ok=True,
                                          delivery="message_sent",
                                          confirmation="reply_started"))
        orig_wait = self.adapter._wait_outbox
        self.adapter._wait_outbox = lambda n, t: None
        try:
            res = self.adapter.send("chatgpt", "late no-id test",
                                    project_id="P-LATE-SCAN",
                                    nonce=nonce, timeout=1)
        finally:
            self.adapter._wait_outbox = orig_wait
        self.assertFalse(res.get("ok"), res)
        self.assertTrue(res.get("uncertain"), res)
        self.assertEqual(res.get("delivery"), "uncertain")
        self.assertTrue(res.get("late"), res)
        self.assertIn("late_evidence", res)

    # -- reconcile_send() after a real late answer --------------------------

    def test_reconcile_upgrades_uncertain_to_sent_late(self):
        # The extension answers 4s after send()'s 2s timeout, so
        # send() returns timeout/UNCERTAIN; reconcile_send() then
        # finds the late receipt (ok:true, message_sent, with a
        # positively-identified message_id) and upgrades it.
        self._start_host(with_extension=True)
        self.send_mode = "confirmed"
        self.send_delay = 4
        res = self.adapter.send("chatgpt", "reconcile late test",
                                project_id="P-RECONCILE", timeout=2)
        self.assertFalse(res.get("ok"), res)
        self.assertTrue(res.get("uncertain"), res)
        self.assertEqual(res.get("error"), "timeout")
        # The receipt lands after send() returned; give the
        # extension time to answer before reconciling.
        time.sleep(3)
        out = self.adapter.reconcile_send(res["message_id"])
        self.assertEqual(out.get("status"), "sent", out)
        self.assertTrue(out.get("late"), out)
        # And a second reconcile still reports sent (idempotent).
        out2 = self.adapter.reconcile_send(res["message_id"])
        self.assertEqual(out2.get("status"), "sent", out2)

    def test_reconcile_uncertain_receipt_stays_uncertain(self):
        self._start_host(with_extension=True)
        self.send_mode = "uncertain"
        self.send_delay = 4
        res = self.adapter.send("chatgpt", "reconcile uncertain test",
                                project_id="P-RECONCILE", timeout=2)
        self.assertTrue(res.get("uncertain"), res)
        time.sleep(3)
        out = self.adapter.reconcile_send(res["message_id"])
        self.assertEqual(out.get("status"), "uncertain", out)
        self.assertTrue(out.get("late"), out)

    def test_reconcile_reply_started_only_stays_uncertain(self):
        # A late receipt with delivery message_sent but NO
        # message_id (reply_started only) does not prove this
        # message was delivered — it stays UNCERTAIN.
        self._start_host(with_extension=True)
        self.send_mode = "confirmed_no_id"
        self.send_delay = 4
        res = self.adapter.send("chatgpt", "reconcile no-id test",
                                project_id="P-RECONCILE", timeout=2)
        self.assertTrue(res.get("uncertain"), res)
        time.sleep(3)
        out = self.adapter.reconcile_send(res["message_id"])
        self.assertEqual(out.get("status"), "uncertain", out)
        self.assertTrue(out.get("late"), out)

    def test_reconcile_not_sent_receipt_marks_failed(self):
        self._start_host(with_extension=True)
        self.send_mode = "not_sent"
        self.send_delay = 4
        res = self.adapter.send("chatgpt", "reconcile not-sent test",
                                project_id="P-RECONCILE", timeout=2)
        self.assertTrue(res.get("uncertain"), res)
        time.sleep(3)
        out = self.adapter.reconcile_send(res["message_id"])
        self.assertEqual(out.get("status"), "not_sent", out)
        self.assertTrue(out.get("late"), out)

    def test_reconcile_unknown_message_id_stays_uncertain(self):
        out = self.adapter.reconcile_send("m-no-such-message")
        self.assertEqual(out.get("status"), "uncertain", out)
        self.assertFalse(out.get("late"), out)

    def test_reconcile_message_id_without_nonce_is_unknown(self):
        out = self.adapter.reconcile_send("not-a-transaction-id")
        self.assertEqual(out.get("status"), "unknown", out)
        self.assertFalse(out.get("late"), out)


if __name__ == "__main__":
    unittest.main()
