#!/usr/bin/env python3
"""RC4 tests for approvals/approvals.py (P0 fix + Condition 1).

RC4: the Muse approval card channel is DISABLED as an execution
authorization source (platform_receipt() raises
platform_receipt_disabled; any hand-built muse_approval_card receipt
is refused). Execution accepts ONLY local-approval-page credentials
(PIN + single-use session token + decision-bound nonce).
Proves:
- platform_receipt() refuses; a hand-built platform receipt is
  refused; an RC3-era platform approval cannot execute;
- approve once -> allow; replay -> deny; expired -> deny; no approval
  -> deny; wrong option -> deny; params digest mismatch -> deny;
  second execution with the same approval -> deny; approver mismatch
  -> deny; session decided_by mismatch -> deny;
- revoke() blocks execution; check_execution re-verifies expiry,
  approved option and the token ceremony at execution time;
- tokens never appear in the store file or the audit log.
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "approvals"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "orchestrator"))
from approvals import (ApprovalStore, _canonical, _sha256,  # noqa: E402
                       local_page_credential, platform_receipt)


def _spec(**over):
    spec = {
        "project_id": "P-001",
        "operation_id": "OP-send-summary",
        "operation_params": {"action": "write_file",
                             "path": "summary.md"},
        "options": ["write", "skip"],
        "recommended_option": "write",
        "evidence": ["round 3 consensus"],
        "cost": "AUD 0",
        "risk": "low",
        "recommendation": "write",
        "approver": "leo",
        "ttl_seconds": 3600,
    }
    spec.update(over)
    return spec


class TestApprovals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store_path = os.path.join(self.tmp.name, "approvals.json")
        self.store = ApprovalStore(self.store_path)

    def tearDown(self):
        self.tmp.cleanup()

    def _create(self, **over):
        spec = _spec(**over)
        return self.store.create_decision(
            project_id=spec["project_id"],
            operation_id=spec["operation_id"],
            operation_params=spec["operation_params"],
            options=spec["options"],
            recommended_option=spec["recommended_option"],
            evidence=spec["evidence"], cost=spec["cost"],
            risk=spec["risk"], recommendation=spec["recommendation"],
            approver=spec["approver"], ttl_seconds=spec["ttl_seconds"])

    def _page_cred(self, decision_id, decided_by="leo"):
        """Build a valid local-page credential the way the page server
        does: register a session (after PIN) and use the decision's
        nonce (read from the store, local machine only)."""
        session = self.store.register_page_session(decided_by)
        data = self.store._load()
        nonce = data["decisions"][decision_id]["page_nonce"]
        return local_page_credential(session["session_token"], nonce,
                                     decided_by)

    # -- happy paths ---------------------------------------------------------

    def test_approve_once_then_execution_allowed(self):
        created = self._create()
        ok, reason = self.store.approve(
            created["decision_id"], created["token"], "write",
            self._page_cred(created["decision_id"]))
        self.assertTrue(ok, reason)
        self.assertEqual(reason, "approved")
        ok, reason = self.store.check_execution(
            created["decision_id"], "OP-send-summary",
            created["operation_params_digest"])
        self.assertTrue(ok, reason)
        self.assertEqual(reason, "allowed")

    def test_local_page_credential_allowed(self):
        created = self._create()
        ok, reason = self.store.approve(
            created["decision_id"], created["token"], "skip",
            self._page_cred(created["decision_id"]))
        self.assertTrue(ok, reason)
        ok, reason = self.store.check_execution(
            created["decision_id"], "OP-send-summary",
            created["operation_params_digest"])
        self.assertTrue(ok, reason)

    # -- Correction 2: caller-declared channel is never trusted -------------

    def test_caller_declared_channel_string_denied(self):
        created = self._create()
        # RC2's old call shape: a bare channel string. Must be refused.
        for bad_cred in ("muse_approval_card", "local_approval_page",
                         {"channel": "muse_approval_card"},
                         {"channel": "muse_approval_card",
                          "receipt": "approved by leo"},
                         {"channel": "chat_text",
                          "receipt": {"decision": "approved"}}):
            ok, reason = self.store.approve(
                created["decision_id"], created["token"], "write",
                bad_cred)
            self.assertFalse(ok, bad_cred)
            self.assertIn(reason, ("credential_not_issued",
                                   "credential_missing_receipt",
                                   "untrusted_channel",
                                   "platform_receipt_disabled"), reason)
        # The decision must still be pending afterwards.
        view = self.store.status(created["decision_id"])
        self.assertEqual(view["status"], "pending")

    # -- RC4 P0: the Muse approval card channel is DISABLED --------------

    def test_platform_receipt_factory_disabled(self):
        # Calling platform_receipt() refuses loudly instead of building
        # a credential that looks valid.
        with self.assertRaises(RuntimeError) as ctx:
            platform_receipt("perm_1", "leo")
        self.assertIn("platform_receipt_disabled", str(ctx.exception))

    def test_hand_built_platform_receipt_denied(self):
        created = self._create()
        # Even a fully-formed platform receipt is refused in RC4.
        cred = {"channel": "muse_approval_card",
                "receipt": {"approval_request_id": "perm_1",
                            "decision": "approved", "decided_by": "leo",
                            "decided_at": "2026-11-19T00:00:00+00:00"}}
        ok, reason = self.store.approve(
            created["decision_id"], created["token"], "write", cred)
        self.assertFalse(ok)
        self.assertEqual(reason, "platform_receipt_disabled")
        view = self.store.status(created["decision_id"])
        self.assertEqual(view["status"], "pending")

    def test_execution_refuses_rc3_platform_approval(self):
        # Defense in depth: an RC3-era decision approved via the
        # platform card (recorded before RC4) must not execute under
        # RC4. Simulate one by writing the RC3 record shape directly.
        created = self._create()
        self.store.approve(created["decision_id"], created["token"],
                           "write", self._page_cred(
                               created["decision_id"]))
        data = self.store._load()
        decision = data["decisions"][created["decision_id"]]
        decision["approved_channel"] = "muse_approval_card"
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        ok, reason = self.store.check_execution(
            created["decision_id"], "OP-send-summary",
            created["operation_params_digest"])
        self.assertFalse(ok)
        self.assertEqual(reason, "execution_channel_not_allowed")

    def test_approver_mismatch_denied(self):
        created = self._create()
        # A session registered for someone else cannot approve a
        # decision whose expected approver is leo.
        ok, reason = self.store.approve(
            created["decision_id"], created["token"], "write",
            self._page_cred(created["decision_id"],
                            decided_by="someone_else"))
        self.assertFalse(ok)
        self.assertEqual(reason, "approver_mismatch")

    def test_session_decided_by_mismatch_denied(self):
        created = self._create()
        session = self.store.register_page_session("leo")
        data = self.store._load()
        nonce = data["decisions"][created["decision_id"]]["page_nonce"]
        cred = local_page_credential(session["session_token"], nonce,
                                     "someone_else")
        ok, reason = self.store.approve(
            created["decision_id"], created["token"], "write", cred)
        self.assertFalse(ok)
        self.assertEqual(reason, "approver_mismatch")

    # -- local page session + nonce ------------------------------------------

    def test_page_session_wrong_nonce_denied(self):
        created = self._create()
        session = self.store.register_page_session("leo")
        cred = local_page_credential(session["session_token"],
                                     "wrong-nonce-value", "leo")
        ok, reason = self.store.approve(
            created["decision_id"], created["token"], "write", cred)
        self.assertFalse(ok)
        self.assertEqual(reason, "page_nonce_mismatch")

    def test_page_session_unknown_token_denied(self):
        created = self._create()
        data = self.store._load()
        nonce = data["decisions"][created["decision_id"]]["page_nonce"]
        cred = local_page_credential("never-registered-token", nonce,
                                     "leo")
        ok, reason = self.store.approve(
            created["decision_id"], created["token"], "write", cred)
        self.assertFalse(ok)
        self.assertEqual(reason, "page_session_not_found")

    def test_page_session_single_use(self):
        created = self._create()
        cred = self._page_cred(created["decision_id"])
        ok, _ = self.store.approve(
            created["decision_id"], created["token"], "write", cred)
        self.assertTrue(ok)
        # Same session token again (second decision): already used.
        created2 = self._create(operation_id="OP-2")
        data = self.store._load()
        nonce2 = data["decisions"][created2["decision_id"]]["page_nonce"]
        cred2 = local_page_credential(
            cred["receipt"]["session_token"], nonce2, "leo")
        ok, reason = self.store.approve(
            created2["decision_id"], created2["token"], "write", cred2)
        self.assertFalse(ok)
        self.assertEqual(reason, "page_session_already_used")

    def test_page_session_expired_denied(self):
        created = self._create()
        session = self.store.register_page_session("leo", ttl_seconds=-1)
        data = self.store._load()
        nonce = data["decisions"][created["decision_id"]]["page_nonce"]
        cred = local_page_credential(session["session_token"], nonce,
                                     "leo")
        ok, reason = self.store.approve(
            created["decision_id"], created["token"], "write", cred)
        self.assertFalse(ok)
        self.assertEqual(reason, "page_session_expired")

    # -- token / gate behaviour (unchanged from RC2) --------------------------

    def test_replay_approve_denied_and_counted(self):
        created = self._create()
        ok, _ = self.store.approve(
            created["decision_id"], created["token"], "write",
            self._page_cred(created["decision_id"]))
        self.assertTrue(ok)
        ok, reason = self.store.approve(
            created["decision_id"], created["token"], "write",
            self._page_cred(created["decision_id"]))
        self.assertFalse(ok)
        self.assertIn(reason, ("token_already_used",
                               "decision_not_pending:approved"))

    def test_second_execution_denied(self):
        created = self._create()
        self.store.approve(created["decision_id"], created["token"],
                           "write", self._page_cred(
                               created["decision_id"]))
        ok, _ = self.store.check_execution(
            created["decision_id"], "OP-send-summary",
            created["operation_params_digest"])
        self.assertTrue(ok)
        ok, reason = self.store.check_execution(
            created["decision_id"], "OP-send-summary",
            created["operation_params_digest"])
        self.assertFalse(ok)
        self.assertEqual(reason, "approval_already_executed")

    def test_no_approval_denied(self):
        created = self._create()
        ok, reason = self.store.check_execution(
            created["decision_id"], "OP-send-summary",
            created["operation_params_digest"])
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("not_approved"))

    def test_expired_token_denied(self):
        created = self._create(ttl_seconds=-1)
        ok, reason = self.store.approve(
            created["decision_id"], created["token"], "write",
            self._page_cred(created["decision_id"]))
        self.assertFalse(ok)
        self.assertEqual(reason, "token_expired")

    def test_expire_overdue(self):
        created = self._create(ttl_seconds=-1)
        expired = self.store.expire_overdue()
        self.assertIn(created["decision_id"], expired)
        view = self.store.status(created["decision_id"])
        self.assertEqual(view["status"], "expired")
        ok, reason = self.store.approve(
            created["decision_id"], created["token"], "write",
            self._page_cred(created["decision_id"]))
        self.assertFalse(ok)

    def test_wrong_token_denied(self):
        created = self._create()
        ok, reason = self.store.approve(
            created["decision_id"], "wrong-token-value", "write",
            self._page_cred(created["decision_id"]))
        self.assertFalse(ok)
        self.assertEqual(reason, "token_mismatch")

    def test_wrong_option_denied(self):
        created = self._create()
        ok, reason = self.store.approve(
            created["decision_id"], created["token"], "delete_everything",
            self._page_cred(created["decision_id"]))
        self.assertFalse(ok)
        self.assertEqual(reason, "option_not_offered")

    def test_params_digest_mismatch_denied(self):
        created = self._create()
        self.store.approve(created["decision_id"], created["token"],
                           "write", self._page_cred(created["decision_id"]))
        other_digest = _sha256(_canonical({"action": "write_file",
                                           "path": "OTHER.md"}))
        ok, reason = self.store.check_execution(
            created["decision_id"], "OP-send-summary", other_digest)
        self.assertFalse(ok)
        self.assertEqual(reason, "params_digest_mismatch")

    def test_operation_id_mismatch_denied(self):
        created = self._create()
        self.store.approve(created["decision_id"], created["token"],
                           "write", self._page_cred(created["decision_id"]))
        ok, reason = self.store.check_execution(
            created["decision_id"], "OP-something-else",
            created["operation_params_digest"])
        self.assertFalse(ok)
        self.assertEqual(reason, "operation_id_mismatch")

    def test_reject_flow_blocks_execution(self):
        created = self._create()
        ok, reason = self.store.reject(
            created["decision_id"], created["token"], "not now",
            self._page_cred(created["decision_id"]))
        self.assertTrue(ok, reason)
        ok, reason = self.store.check_execution(
            created["decision_id"], "OP-send-summary",
            created["operation_params_digest"])
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("not_approved"))

    # -- RC4 Condition 1: execution-time re-verification -------------------

    def test_revoke_blocks_execution(self):
        created = self._create()
        self.store.approve(created["decision_id"], created["token"],
                           "write", self._page_cred(
                               created["decision_id"]))
        ok, reason = self.store.revoke(created["decision_id"],
                                       "approver changed their mind")
        self.assertTrue(ok, reason)
        ok, reason = self.store.check_execution(
            created["decision_id"], "OP-send-summary",
            created["operation_params_digest"])
        self.assertFalse(ok)
        self.assertEqual(reason, "not_approved:revoked")

    def test_execution_reverifies_expired_approval(self):
        # Approved in time, but the deadline passes before execution:
        # the gate re-reads the deadline and refuses.
        created = self._create()
        self.store.approve(created["decision_id"], created["token"],
                           "write", self._page_cred(
                               created["decision_id"]))
        data = self.store._load()
        data["decisions"][created["decision_id"]][
            "deadline"] = "2000-01-01T00:00:00+00:00"
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        ok, reason = self.store.check_execution(
            created["decision_id"], "OP-send-summary",
            created["operation_params_digest"])
        self.assertFalse(ok)
        self.assertEqual(reason, "expired")

    def test_execution_reverifies_approved_option(self):
        # The stored approved option is tampered with after approval:
        # the gate must notice it is no longer an offered option.
        created = self._create()
        self.store.approve(created["decision_id"], created["token"],
                           "write", self._page_cred(
                               created["decision_id"]))
        data = self.store._load()
        data["decisions"][created["decision_id"]][
            "approved_option"] = "delete_everything"
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        ok, reason = self.store.check_execution(
            created["decision_id"], "OP-send-summary",
            created["operation_params_digest"])
        self.assertFalse(ok)
        self.assertEqual(reason, "approved_option_invalid")

    def test_execution_refuses_unceremonied_approval(self):
        # A decision record hand-flipped to "approved" without the
        # token ceremony (token never consumed) must not execute.
        created = self._create()
        data = self.store._load()
        decision = data["decisions"][created["decision_id"]]
        decision["status"] = "approved"
        decision["approved_channel"] = "local_approval_page"
        decision["approved_option"] = "write"
        decision["token_used"] = False
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        ok, reason = self.store.check_execution(
            created["decision_id"], "OP-send-summary",
            created["operation_params_digest"])
        self.assertFalse(ok)
        self.assertEqual(reason, "approval_token_not_consumed")

    def test_tokens_never_in_logs(self):
        # After a full local-page approval, neither the raw approval
        # token nor the raw session token may appear anywhere in the
        # store file (decisions, sessions, audit log).
        created = self._create()
        cred = self._page_cred(created["decision_id"])
        session_token = cred["receipt"]["session_token"]
        ok, reason = self.store.approve(
            created["decision_id"], created["token"], "write", cred)
        self.assertTrue(ok, reason)
        with open(self.store_path, "r", encoding="utf-8") as f:
            raw = f.read()
        self.assertNotIn(created["token"], raw)
        self.assertNotIn(session_token, raw)
        # The audit redaction itself: a sensitive field is scrubbed.
        self.store.record_event("test_event",
                                token="SECRET-TOKEN-VALUE",
                                session_token="SECRET-SESSION-VALUE",
                                note="harmless")
        with open(self.store_path, "r", encoding="utf-8") as f:
            raw = f.read()
        self.assertNotIn("SECRET-TOKEN-VALUE", raw)
        self.assertNotIn("SECRET-SESSION-VALUE", raw)
        self.assertIn("[redacted]", raw)
        self.assertIn("harmless", raw)

    def test_token_never_stored_in_plain(self):
        created = self._create()
        with open(self.store_path, "r", encoding="utf-8") as f:
            raw = f.read()
        self.assertNotIn(created["token"], raw)
        data = json.loads(raw)
        stored = data["decisions"][created["decision_id"]]
        self.assertIn("token_hash", stored)
        self.assertNotIn("token", stored)
        self.assertIn("page_nonce", stored)
        # The hash is the sha256 of the namespaced token.
        self.assertEqual(
            stored["token_hash"],
            hashlib.sha256(
                ("agent-relay-approval-token:" + created["token"]
                 ).encode("utf-8")).hexdigest())

    def test_status_hides_token_hash_and_nonce(self):
        created = self._create()
        view = self.store.status(created["decision_id"])
        self.assertNotIn("token_hash", view)
        self.assertNotIn("page_nonce", view)


if __name__ == "__main__":
    unittest.main()
