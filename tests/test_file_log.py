#!/usr/bin/env python3
"""RC2 tests for orchestrator/file_log.py.

Covers RC1 behaviour (append / count / verify / tamper / oversize) plus
the RC2 fixes: strict dedup (message_id, nonce), the send transaction
(intent -> success/failed), outcome-without-intent rejection, duplicate
outcome rejection, and restart reconciliation incl. UNCERTAIN.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "orchestrator"))
import file_log  # noqa: E402


class TestFileLogBasics(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.tmp.name, "discussion.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_count_verify(self):
        r1 = file_log.append_record(self.log, {
            "kind": "message", "project_id": "P-1", "message_id": "m-1",
            "nonce": "n-1", "sender": "muse", "turn_number": 1,
            "content": "hello", "status": "sent"})
        r2 = file_log.append_record(self.log, {
            "kind": "message", "project_id": "P-1", "message_id": "m-2",
            "nonce": "n-2", "sender": "chatgpt", "turn_number": 2,
            "content": "hi", "status": "received"})
        self.assertEqual(r1["seq"], 1)
        self.assertEqual(r2["seq"], 2)
        self.assertEqual(len(file_log.read_records(self.log)), 2)
        self.assertEqual(file_log.verify_log(self.log)["ok"], True)

    def test_tamper_detected(self):
        file_log.append_record(self.log, {
            "kind": "message", "project_id": "P-1", "message_id": "m-1",
            "nonce": "n-1", "content": "hello"})
        with open(self.log, "r", encoding="utf-8") as f:
            lines = f.readlines()
        rec = json.loads(lines[0])
        rec["content"] = "tampered"
        lines[0] = json.dumps(rec, ensure_ascii=False) + "\n"
        with open(self.log, "w", encoding="utf-8") as f:
            f.writelines(lines)
        result = file_log.verify_log(self.log)
        self.assertFalse(result["ok"])
        problems = {p["problem"] for p in result["problems"]}
        self.assertIn("hash_mismatch", problems)
        self.assertIn("length_mismatch", problems)

    def test_oversize_content_rejected(self):
        with self.assertRaises(ValueError):
            file_log.append_record(self.log, {
                "kind": "message", "message_id": "m-1", "nonce": "n-1",
                "content": "x" * (file_log.MAX_CONTENT_CHARS + 1)})


class TestFileLogDedup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.tmp.name, "discussion.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_duplicate_message_id_rejected(self):
        file_log.append_record(self.log, {
            "kind": "message", "message_id": "m-1", "nonce": "n-1",
            "content": "one"})
        with self.assertRaises(ValueError):
            file_log.append_record(self.log, {
                "kind": "message", "message_id": "m-1", "nonce": "n-2",
                "content": "two"})
        self.assertEqual(len(file_log.read_records(self.log)), 1)

    def test_duplicate_nonce_rejected(self):
        file_log.append_record(self.log, {
            "kind": "message", "message_id": "m-1", "nonce": "n-1",
            "content": "one"})
        with self.assertRaises(ValueError):
            file_log.append_record(self.log, {
                "kind": "message", "message_id": "m-2", "nonce": "n-1",
                "content": "two"})

    def test_duplicate_intent_rejected(self):
        file_log.send_intent(self.log, "P-1", "m-1", "n-1")
        with self.assertRaises(ValueError):
            file_log.send_intent(self.log, "P-1", "m-1", "n-1")


class TestSendTransaction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.tmp.name, "discussion.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_intent_then_success(self):
        file_log.send_intent(self.log, "P-1", "m-1", "n-1")
        self.assertEqual(file_log.pending_intents(self.log), ["m-1"])
        file_log.send_confirm(self.log, "m-1", "sent")
        self.assertEqual(file_log.pending_intents(self.log), [])
        kinds = [r["kind"] for r in file_log.read_records(self.log)]
        self.assertEqual(kinds, ["send_intent", "send_success"])

    def test_confirm_without_intent_rejected(self):
        with self.assertRaises(ValueError):
            file_log.send_confirm(self.log, "m-1", "sent")

    def test_duplicate_outcome_rejected(self):
        file_log.send_intent(self.log, "P-1", "m-1", "n-1")
        file_log.send_confirm(self.log, "m-1", "sent")
        with self.assertRaises(ValueError):
            file_log.send_confirm(self.log, "m-1", "failed")
        with self.assertRaises(ValueError):
            file_log.mark_uncertain(self.log, "m-1", "too late")

    def test_reconcile_sent(self):
        file_log.send_intent(self.log, "P-1", "m-1", "n-1")
        result = file_log.reconcile(self.log, verify_fn=lambda mid: "sent")
        self.assertEqual(result["uncertain"], [])
        self.assertEqual(result["reconciled"][0]["verdict"], "sent")
        self.assertEqual(file_log.pending_intents(self.log), [])

    def test_reconcile_not_sent(self):
        file_log.send_intent(self.log, "P-1", "m-1", "n-1")
        result = file_log.reconcile(self.log,
                                    verify_fn=lambda mid: "not_sent")
        self.assertEqual(result["reconciled"][0]["verdict"], "not_sent")
        self.assertEqual(file_log.pending_intents(self.log), [])

    def test_reconcile_unknown_marks_uncertain(self):
        file_log.send_intent(self.log, "P-1", "m-1", "n-1")
        result = file_log.reconcile(self.log,
                                    verify_fn=lambda mid: "unknown")
        self.assertEqual(result["uncertain"], ["m-1"])
        self.assertEqual(len(file_log.list_uncertain(self.log)), 1)
        # A second reconcile must not re-mark it (already settled).
        result2 = file_log.reconcile(self.log,
                                     verify_fn=lambda mid: "unknown")
        self.assertEqual(result2["uncertain"], [])
        self.assertEqual(len(file_log.list_uncertain(self.log)), 1)

    def test_reconcile_no_verify_fn_marks_uncertain(self):
        file_log.send_intent(self.log, "P-1", "m-1", "n-1")
        result = file_log.reconcile(self.log)
        self.assertEqual(result["uncertain"], ["m-1"])

    # HOTFIX 5 (P2): send_reconciled — the only way to upgrade an
    # UNCERTAIN transaction after its outcome was recorded. The
    # one-outcome rule forbids a second send_success / send_failed
    # / send_uncertain, so the upgrade is a separate kind.
    def test_reconciled_after_uncertain(self):
        file_log.send_intent(self.log, "P-1", "m-1", "n-1")
        file_log.mark_uncertain(self.log, "m-1", "no confirmation")
        rec = file_log.send_reconciled(
            self.log, "m-1", "sent",
            reason="late receipt proves delivery",
            evidence={"message_id": "msg-1"})
        self.assertEqual(rec["kind"], "send_reconciled")
        self.assertEqual(rec["status"], "sent")
        kinds = [r["kind"] for r in file_log.read_records(self.log)]
        self.assertEqual(kinds, ["send_intent", "send_uncertain",
                                 "send_reconciled"])

    def test_reconciled_without_intent_rejected(self):
        with self.assertRaises(ValueError):
            file_log.send_reconciled(self.log, "m-1", "sent")

    def test_reconciled_without_uncertain_rejected(self):
        # After a terminal send_success the transaction is final;
        # it cannot be "reconciled" afterwards.
        file_log.send_intent(self.log, "P-1", "m-1", "n-1")
        file_log.send_confirm(self.log, "m-1", "sent")
        with self.assertRaises(ValueError):
            file_log.send_reconciled(self.log, "m-1", "failed")

    def test_reconciled_twice_rejected(self):
        file_log.send_intent(self.log, "P-1", "m-1", "n-1")
        file_log.mark_uncertain(self.log, "m-1", "no confirmation")
        file_log.send_reconciled(self.log, "m-1", "sent")
        with self.assertRaises(ValueError):
            file_log.send_reconciled(self.log, "m-1", "failed")

    def test_reconciled_bad_outcome_rejected(self):
        file_log.send_intent(self.log, "P-1", "m-1", "n-1")
        file_log.mark_uncertain(self.log, "m-1", "no confirmation")
        with self.assertRaises(ValueError):
            file_log.send_reconciled(self.log, "m-1", "uncertain")


if __name__ == "__main__":
    unittest.main()
