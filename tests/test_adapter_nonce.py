#!/usr/bin/env python3
"""RC4-hotfix tests for the nonce contract (FIX 1 + FIX 4) at the
adapter level.

Drives ping, health, and read_latest through transport/adapter.py
against the real native host (transport/native_host.py), with this
test playing the extension side over the host's stdin/stdout pipes
— the same shape content.js now produces (FIX 1: every reply echoes
the request nonce; FIX 4: send_result carries an explicit delivery
state, "message_sent" vs "uncertain" vs "not_sent").

Checks:
- ping: the pong recorded in the outbox carries the request nonce,
  so Adapter._wait_outbox() finds it (before FIX 1 only the send
  path echoed the nonce, so health/read_latest timed out even when
  the browser had responded);
- health / read_latest: the returned envelope nonce matches the
  request nonce (not a timeout);
- a reply WITHOUT a nonce never matches _wait_outbox() (the matcher
  requires the nonce);
- send: a confirmed send returns ok:true with delivery
  "message_sent" (MESSAGE_SENT only, never RESPONSE_COMPLETED); an
  unconfirmed send returns uncertain:true with delivery "uncertain";
  a definitely-not-sent send returns delivery "not_sent".
"""

import hashlib
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
REPLY_TEXT = "Hello from ChatGPT"


def _sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestAdapterNonce(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # Adapter skill root: state lives under orchestrator/state,
        # native-host queue under orchestrator/state/native_host.
        self.skill_root = os.path.join(self.tmp.name, "skill")
        self.nh_dir = os.path.join(
            self.skill_root, "orchestrator", "state", "native_host")
        os.makedirs(self.nh_dir, exist_ok=True)
        self.proc = subprocess.Popen(
            [sys.executable, HOST, "--state-dir", self.nh_dir],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        # Wait for the host's secret and heartbeat (it writes the
        # heartbeat on its first loop iteration).
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
        self.adapter = Adapter(self.skill_root, mode="native_host")
        self.assertTrue(self.adapter.native_host_connected(),
                        "native host heartbeat is not fresh")
        # The extension side: read forwarded commands from the host's
        # stdout and answer them the way content.js now does (FIX 1:
        # every reply echoes the nonce; FIX 4: explicit delivery).
        self.send_mode = "confirmed"  # confirmed | uncertain | not_sent
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._extension_loop,
                                        daemon=True)
        self._thread.start()

    def tearDown(self):
        self._stop.set()
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

    def _extension_loop(self):
        while not self._stop.is_set():
            try:
                msg = read_msg(self.proc, timeout=2)
            except Exception:
                return
            if msg is None:
                return  # EOF / host exited
            if not isinstance(msg, dict):
                continue
            nonce = msg.get("nonce")
            mtype = msg.get("type")
            try:
                if mtype == "ping":
                    write_msg(self.proc, {
                        "type": "pong",
                        "origin": "https://chatgpt.com",
                        "nonce": nonce})
                elif mtype == "health":
                    write_msg(self.proc, {
                        "type": "health_result",
                        "origin": "https://chatgpt.com",
                        "nonce": nonce,
                        "ok": True,
                        "composer_found": True,
                        "send_button_found": True,
                        "streaming": False})
                elif mtype == "read_latest":
                    write_msg(self.proc, {
                        "type": "read_result",
                        "origin": "https://chatgpt.com",
                        "nonce": nonce,
                        "found": True,
                        "sender": "chatgpt",
                        "content": REPLY_TEXT,
                        "content_sha256": _sha256(REPLY_TEXT),
                        "content_len": len(REPLY_TEXT),
                        "streaming": False})
                elif mtype == "send":
                    if self.send_mode == "uncertain":
                        write_msg(self.proc, {
                            "type": "send_result",
                            "origin": "https://chatgpt.com",
                            "nonce": nonce,
                            "ok": False,
                            "delivery": "uncertain",
                            "error": "send_unconfirmed"})
                    elif self.send_mode == "not_sent":
                        write_msg(self.proc, {
                            "type": "send_result",
                            "origin": "https://chatgpt.com",
                            "nonce": nonce,
                            "ok": False,
                            "delivery": "not_sent",
                            "error": "composer_or_send_button_missing"})
                    else:
                        write_msg(self.proc, {
                            "type": "send_result",
                            "origin": "https://chatgpt.com",
                            "nonce": nonce,
                            "ok": True,
                            "delivery": "message_sent"})
            except (BrokenPipeError, ValueError, OSError):
                return

    def test_ping_pong_nonce_matches(self):
        nonce = "n-ping-test-1"
        self.adapter._write_command({"id": "cmd-" + nonce,
                                     "type": "ping", "nonce": nonce})
        rec = self.adapter._wait_outbox(nonce, timeout=5)
        self.assertIsNotNone(
            rec, "pong was not matched by nonce (FIX 1 regression)")
        env = rec.get("envelope") or {}
        self.assertEqual(env.get("type"), "pong")
        self.assertEqual(env.get("nonce"), nonce)

    def test_health_echoes_nonce(self):
        res = self.adapter.health("chatgpt")
        self.assertTrue(res.get("ok"), res)
        # The returned detail must carry the SAME nonce the adapter
        # sent — not a timeout, not another command's reply.
        self.assertEqual(res["detail"].get("nonce"), res["nonce"])
        self.assertTrue(res["detail"].get("composer_found"))

    def test_read_latest_echoes_nonce(self):
        res = self.adapter.read_latest("chatgpt")
        self.assertTrue(res.get("ok"), res)
        self.assertTrue(res.get("found"), res)
        self.assertEqual(res.get("content"), REPLY_TEXT)
        self.assertEqual(res.get("content_sha256"), _sha256(REPLY_TEXT))
        self.assertTrue(res.get("nonce"))

    def test_nonce_less_reply_never_matches(self):
        # A reply without a nonce must NOT satisfy _wait_outbox():
        # before FIX 1 the browser answered without a nonce and the
        # adapter timed out waiting for a match. The matcher must
        # require the nonce, not accept any reply.
        outbox = os.path.join(self.nh_dir, "outbox.jsonl")
        with open(outbox, "a", encoding="utf-8") as f:
            f.write(json.dumps(
                {"direction": "extension_to_coordinator",
                 "envelope": {"type": "pong"}}) + "\n")
        rec = self.adapter._wait_outbox("nonce-that-never-comes",
                                        timeout=1)
        self.assertIsNone(rec, "a nonce-less reply matched the waiter")

    def test_send_confirmed_is_message_sent(self):
        res = self.adapter.send("chatgpt", "hello relay",
                                project_id="P-NONCE")
        self.assertTrue(res.get("ok"), res)
        # ok:true means MESSAGE_SENT only — never RESPONSE_COMPLETED.
        self.assertEqual(res.get("delivery"), "message_sent")
        self.assertTrue(res.get("message_id", "").startswith("m-"))
        # The send transaction recorded a success in the state log.
        log = os.path.join(self.skill_root, "orchestrator", "state",
                           "discussion.jsonl")
        kinds = [r.get("kind") for r in file_log.read_records(log)
                 if r.get("message_id") == res["message_id"]]
        self.assertIn("send_success", kinds)

    def test_send_unconfirmed_is_uncertain(self):
        self.send_mode = "uncertain"
        res = self.adapter.send("chatgpt", "will not appear",
                                project_id="P-NONCE")
        self.assertFalse(res.get("ok"), res)
        self.assertTrue(res.get("uncertain"), res)
        self.assertEqual(res.get("delivery"), "uncertain")
        self.assertEqual(res.get("error"), "send_unconfirmed")

    def test_send_not_sent_is_failed(self):
        self.send_mode = "not_sent"
        res = self.adapter.send("chatgpt", "no composer",
                                project_id="P-NONCE")
        self.assertFalse(res.get("ok"), res)
        self.assertFalse(res.get("uncertain", False), res)
        self.assertEqual(res.get("delivery"), "not_sent")
        self.assertEqual(res.get("error"),
                         "composer_or_send_button_missing")


if __name__ == "__main__":
    unittest.main()
