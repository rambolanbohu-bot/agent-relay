#!/usr/bin/env python3
"""RC4 tests for approvals/local_approval_page.py (P0 fix + Condition 1).

Starts the REAL local approval page server on 127.0.0.1 (ephemeral
port) and drives it with http.client — no mocks of the HTTP layer:
- wrong PIN -> 403, no session, nothing recorded;
- PIN -> session cookie -> decision form shows the decision;
- approve with session + nonce + token + option -> recorded, and the
  execution gate then allows it;
- the same session cannot approve a second decision (single-use);
- wrong nonce -> 403; wrong token -> 403; no session -> 403;
- PIN is stored only as a salted hash (the raw PIN never appears in
  the pin file);
- RC4: repeated wrong PINs lock the PIN out (and the lockout is
  recorded in the audit log); an expired session token is refused;
  no raw token appears in the store file after a full approval;
  verify_pin is only ever called from this page's /pin handler
  (source scan over the package).
"""

import http.client
import json
import os
import re
import sys
import tempfile
import threading
import time
import unittest
from urllib.parse import urlencode

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "approvals"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "orchestrator"))
import local_approval_page as page_mod  # noqa: E402
from approvals import ApprovalStore  # noqa: E402
from local_approval_page import (LocalApprovalPage, set_pin,  # noqa: E402
                                 verify_pin)


class TestLocalPage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store_path = os.path.join(self.tmp.name, "approvals.json")
        self.pin_file = os.path.join(self.tmp.name, "approval_pin.json")
        self.pin = set_pin(self.pin_file)
        self.store = ApprovalStore(self.store_path)
        self.created = self.store.create_decision(
            project_id="P-001", operation_id="OP-send-summary",
            operation_params={"action": "write_file",
                              "path": "summary.md"},
            options=["write", "skip"], recommended_option="write",
            evidence=["round 3 consensus"], cost="AUD 0", risk="low",
            recommendation="write", approver="leo", ttl_seconds=3600)
        self.did = self.created["decision_id"]
        self.page = LocalApprovalPage(self.store_path, self.pin_file,
                                      approver="leo", port=0)
        self.thread = threading.Thread(
            target=self.page.serve_forever, daemon=True)
        self.thread.start()
        # Wait for the server to bind (serve_forever sets .server first).
        for _ in range(100):
            if self.page.server is not None:
                break
            import time
            time.sleep(0.01)
        self.assertIsNotNone(self.page.server)
        self.port = self.page.server.server_port
        self.cookies = {}

    def tearDown(self):
        if self.page.server is not None:
            self.page.server.shutdown()
            self.page.server.server_close()
        self.tmp.cleanup()

    # -- http helpers ---------------------------------------------------------

    def _req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port,
                                          timeout=10)
        hdrs = dict(headers or {})
        if self.cookies:
            hdrs["Cookie"] = "; ".join(f"{k}={v}"
                                       for k, v in self.cookies.items())
        conn.request(method, path, body=body, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read().decode("utf-8", "replace")
        set_cookie = resp.getheader("Set-Cookie")
        if set_cookie:
            for part in set_cookie.split(";"):
                part = part.strip()
                if "=" in part and " " not in part:
                    k, v = part.split("=", 1)
                    if v:
                        self.cookies[k] = v
                    else:
                        self.cookies.pop(k, None)
        conn.close()
        return resp.status, resp.getheader("Location"), data

    def _pin_and_session(self, pin=None):
        body = urlencode({"decision_id": self.did,
                          "pin": pin if pin is not None else self.pin})
        return self._req("POST", "/pin", body,
                         {"Content-Type":
                          "application/x-www-form-urlencoded"})

    def _approve(self, token, option="write", nonce=None, did=None):
        if nonce is None:
            data = self.store._load()
            nonce = data["decisions"][self.did]["page_nonce"]
        body = urlencode({"decision_id": did or self.did, "token": token,
                          "option": option, "page_nonce": nonce})
        return self._req("POST", "/approve", body,
                         {"Content-Type":
                          "application/x-www-form-urlencoded"})

    # -- tests ------------------------------------------------------------------

    def test_pin_file_stores_only_hash(self):
        with open(self.pin_file, "r", encoding="utf-8") as f:
            record = json.load(f)
        # The PIN must only ever appear as its salted hash, never raw.
        # Check whole values, not raw substrings: the created_at
        # timestamp carries 6-digit microseconds that can coincidentally
        # equal the 6-digit PIN (e.g. "...32.228532+00:00"), which a
        # substring search would report as a leak.
        self.assertEqual(set(record.keys()),
                         {"salt", "pin_hash", "created_at"})
        self.assertNotIn(self.pin, record.values())
        self.assertTrue(verify_pin(self.pin_file, self.pin))
        self.assertFalse(verify_pin(self.pin_file, "000000"))

    def test_wrong_pin_no_session(self):
        status, _, _ = self._pin_and_session(pin="000000")
        self.assertEqual(status, 403)
        self.assertNotIn("ar_session", self.cookies)
        view = self.store.status(self.did)
        self.assertEqual(view["status"], "pending")

    def test_full_flow_approve_then_gate_allows(self):
        # 1. List page shows the pending decision.
        status, _, body = self._req("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(self.did, body)
        # 2. Decision page without a session asks for the PIN.
        status, _, body = self._req(
            "GET", f"/decision?decision_id={self.did}")
        self.assertEqual(status, 200)
        self.assertIn("PIN", body)
        # 3. PIN -> session cookie + redirect to the decision page.
        status, location, _ = self._pin_and_session()
        self.assertEqual(status, 303)
        self.assertIn(self.did, location or "")
        self.assertIn("ar_session", self.cookies)
        # 4. Decision page now shows the approval form (with the nonce).
        status, _, body = self._req(
            "GET", f"/decision?decision_id={self.did}")
        self.assertEqual(status, 200)
        self.assertIn("page_nonce", body)
        # 5. Approve with the session + nonce + token + option.
        status, _, body = self._approve(self.created["token"])
        self.assertEqual(status, 200, body)
        self.assertIn("已批准", body)
        view = self.store.status(self.did)
        self.assertEqual(view["status"], "approved")
        self.assertEqual(view["approved_channel"], "local_approval_page")
        self.assertEqual(view["decided_by"], "leo")
        # 6. The execution gate now allows this exact operation.
        ok, reason = self.store.check_execution(
            self.did, "OP-send-summary",
            self.created["operation_params_digest"])
        self.assertTrue(ok, reason)

    def test_session_single_use(self):
        self._pin_and_session()
        status, _, _ = self._approve(self.created["token"])
        self.assertEqual(status, 200)
        # A second decision with the same (now consumed) session: the
        # page must ask for the PIN again, and a direct approve fails.
        created2 = self.store.create_decision(
            project_id="P-001", operation_id="OP-2",
            operation_params={"action": "write_file", "path": "b.md"},
            options=["write", "skip"], recommended_option="write",
            evidence=[], cost="AUD 0", risk="low", recommendation="write",
            approver="leo", ttl_seconds=3600)
        status, _, _ = self._approve(created2["token"],
                                     did=created2["decision_id"])
        self.assertEqual(status, 403)
        view = self.store.status(created2["decision_id"])
        self.assertEqual(view["status"], "pending")

    def test_approve_without_session_denied(self):
        status, _, _ = self._approve(self.created["token"])
        self.assertEqual(status, 403)
        view = self.store.status(self.did)
        self.assertEqual(view["status"], "pending")

    def test_wrong_nonce_denied(self):
        self._pin_and_session()
        status, _, body = self._approve(self.created["token"],
                                        nonce="forged-nonce")
        self.assertEqual(status, 403)
        self.assertIn("page_nonce_mismatch", body)
        view = self.store.status(self.did)
        self.assertEqual(view["status"], "pending")

    def test_wrong_token_denied(self):
        self._pin_and_session()
        status, _, body = self._approve("wrong-token")
        self.assertEqual(status, 403)
        self.assertIn("token_mismatch", body)
        view = self.store.status(self.did)
        self.assertEqual(view["status"], "pending")

    def test_reject_flow(self):
        self._pin_and_session()
        body = urlencode({"decision_id": self.did,
                          "token": self.created["token"],
                          "reason": "not now",
                          "page_nonce": self.store._load()["decisions"]
                          [self.did]["page_nonce"]})
        status, _, resp_body = self._req(
            "POST", "/reject", body,
            {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(status, 200, resp_body)
        self.assertIn("已拒绝", resp_body)
        view = self.store.status(self.did)
        self.assertEqual(view["status"], "rejected")
        ok, reason = self.store.check_execution(
            self.did, "OP-send-summary",
            self.created["operation_params_digest"])
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("not_approved"))

    # -- RC4 Condition 1: PIN lockout, session expiry, token hygiene -----

    def test_wrong_pin_lockout(self):
        # Shrink the windows for the test (production: 5 in 15 min,
        # lockout 15 min). The lockout state lives in a file next to
        # the PIN file, mode 0600.
        orig = (page_mod.MAX_PIN_ATTEMPTS,
                page_mod.PIN_ATTEMPT_WINDOW_SECONDS,
                page_mod.PIN_LOCKOUT_SECONDS)
        page_mod.MAX_PIN_ATTEMPTS = 3
        page_mod.PIN_ATTEMPT_WINDOW_SECONDS = 3600
        page_mod.PIN_LOCKOUT_SECONDS = 2
        try:
            status, _, body = self._pin_and_session(pin="000000")
            self.assertEqual(status, 403)
            self.assertIn("PIN 不对", body)
            status, _, body = self._pin_and_session(pin="111111")
            self.assertEqual(status, 403)
            self.assertIn("PIN 不对", body)
            # Third failure trips the lockout.
            status, _, body = self._pin_and_session(pin="222222")
            self.assertEqual(status, 403)
            self.assertIn("已锁定", body)
            # Even the CORRECT PIN is refused while locked.
            status, _, body = self._pin_and_session()
            self.assertEqual(status, 403)
            self.assertIn("已锁定", body)
            self.assertNotIn("ar_session", self.cookies)
            # The lockout is recorded in the audit log (no PIN value).
            data = self.store._load()
            events = [e["event"] for e in data.get("audit", [])]
            self.assertIn("pin_lockout", events)
            with open(self.store_path, "r", encoding="utf-8") as f:
                raw = f.read()
            self.assertNotIn("000000", raw)
            self.assertNotIn("111111", raw)
            self.assertNotIn("222222", raw)
            # After the lockout window passes, the correct PIN works.
            time.sleep(2.2)
            status, location, _ = self._pin_and_session()
            self.assertEqual(status, 303)
            self.assertIn("ar_session", self.cookies)
        finally:
            (page_mod.MAX_PIN_ATTEMPTS,
             page_mod.PIN_ATTEMPT_WINDOW_SECONDS,
             page_mod.PIN_LOCKOUT_SECONDS) = orig

    def test_expired_session_token_refused(self):
        # A session registered with an already-expired TTL cannot
        # approve, even with the right nonce and token.
        session = self.store.register_page_session("leo", ttl_seconds=-1)
        self.cookies["ar_session"] = session["session_token"]
        status, _, body = self._approve(self.created["token"])
        self.assertEqual(status, 403)
        self.assertIn("page_session_expired", body)
        view = self.store.status(self.did)
        self.assertEqual(view["status"], "pending")

    def test_tokens_absent_from_store_after_flow(self):
        # After a full approve flow, neither the raw approval token nor
        # the raw session token may appear anywhere in the store file.
        status, _, _ = self._pin_and_session()
        self.assertEqual(status, 303)
        session_token = self.cookies.get("ar_session")
        self.assertTrue(session_token)
        status, _, _ = self._approve(self.created["token"])
        self.assertEqual(status, 200)
        with open(self.store_path, "r", encoding="utf-8") as f:
            store = json.load(f)
        # Walk every string value in the store: a leaked secret would
        # appear as a whole value. A raw substring search is unsafe
        # for the 6-digit PIN — ISO timestamps carry 6-digit
        # microsecond fields that can coincidentally equal it (this
        # test failed once on "...32.228532+00:00"). The two long
        # tokens are also checked as substrings: a 43-char random
        # token cannot false-positive on a timestamp.
        values = []

        def _walk(node):
            if isinstance(node, str):
                values.append(node)
            elif isinstance(node, dict):
                for v in node.values():
                    _walk(v)
            elif isinstance(node, list):
                for v in node:
                    _walk(v)

        _walk(store)
        for secret in (self.created["token"], session_token, self.pin):
            self.assertNotIn(secret, values)
        with open(self.store_path, "r", encoding="utf-8") as f:
            raw = f.read()
        self.assertNotIn(self.created["token"], raw)
        self.assertNotIn(session_token, raw)

    def test_pin_only_in_trusted_ui(self):
        # Static guarantee (RC4, Condition 1): the PIN is only ever
        # verified in this page's /pin handler. Scan every Python file
        # in the package (excluding the tests themselves): verify_pin(
        # may only appear in approvals/local_approval_page.py.
        pkg = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for root, dirs, files in os.walk(pkg):
            dirs[:] = [d for d in dirs
                       if d not in ("__pycache__", "tests")]
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
                if "verify_pin(" in text and not path.endswith(
                        os.path.join("approvals",
                                     "local_approval_page.py")):
                    offenders.append(path)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
