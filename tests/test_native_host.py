#!/usr/bin/env python3
"""RC2 tests for transport/native_host.py (condition 2).

The test script plays the extension side: it spawns the native host as a
subprocess, drives a message through it, and reads the reply — proving the
extension <-> coordinator round trip works locally in simulated form:
  coordinator (inbox file) -> host -> extension (stdout pipe)
  extension (stdin pipe) -> host -> coordinator (outbox file)
It also checks the shared-secret auth (bad auth is refused) and that the
secret file is created mode 0600.
"""

import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
HOST = os.path.join(PKG, "transport", "native_host.py")


sys.path.insert(0, os.path.join(PKG, "windows_e2e_test"))
from native_host_driver import _StdoutReader


def read_msg(proc, timeout=5):
    if not hasattr(proc, "_test_stdout_reader"):
        proc._test_stdout_reader = _StdoutReader(proc.stdout)
        proc._test_stdout_reader.start()
    return proc._test_stdout_reader.next(timeout)


def write_msg(proc, obj):
    raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    proc.stdin.write(struct.pack("<I", len(raw)) + raw)
    proc.stdin.flush()


def _wait_file_contains(path, predicate, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            if predicate(json.loads(line)):
                                return True
                        except ValueError:
                            continue
        except FileNotFoundError:
            pass
        time.sleep(0.1)
    return False


class TestNativeHost(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = os.path.join(self.tmp.name, "native_host")
        os.makedirs(self.state_dir, exist_ok=True)
        self.proc = subprocess.Popen(
            [sys.executable, HOST, "--state-dir", self.state_dir],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        # The host creates the secret on startup; wait for it.
        deadline = time.time() + 5
        while time.time() < deadline:
            if os.path.exists(os.path.join(self.state_dir, "secret")):
                break
            time.sleep(0.1)
        with open(os.path.join(self.state_dir, "secret"), "r",
                  encoding="ascii") as f:
            self.secret = f.read().strip()
        self.inbox = os.path.join(self.state_dir, "inbox.jsonl")
        self.outbox = os.path.join(self.state_dir, "outbox.jsonl")

    def tearDown(self):
        try:
            self.proc.stdin.close()
        except (BrokenPipeError, ValueError):
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        reader = getattr(self.proc, "_test_stdout_reader", None)
        if reader is not None:
            reader.join(timeout=5)
        self.proc.stdout.close()
        self.proc.stderr.close()
        self.tmp.cleanup()

    def _append_inbox(self, cmd):
        with open(self.inbox, "a", encoding="utf-8") as f:
            f.write(json.dumps(cmd, ensure_ascii=False) + "\n")

    def test_secret_file_mode_0600(self):
        path = os.path.join(self.state_dir, "secret")
        self.assertRegex(self.secret, re.compile(r"^[0-9a-f]{64}$"))
        if os.name == "nt":
            # Windows stat cannot represent POSIX access bits. Verify the
            # creation request without claiming it verifies Windows ACLs.
            sys.path.insert(0, os.path.dirname(HOST))
            self.addCleanup(sys.path.pop, 0)
            from native_host import _load_secret
            with tempfile.TemporaryDirectory() as state:
                with patch("native_host.os.open", wraps=os.open) as open_file:
                    _load_secret(state)
                self.assertEqual(open_file.call_args.args[2], 0o600)
        else:
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_coordinator_to_extension_forward(self):
        self._append_inbox({"id": "cmd-1", "type": "send", "site": "chatgpt",
                            "text": "hello from coordinator",
                            "nonce": "nonce-1", "auth": self.secret})
        msg = read_msg(self.proc, timeout=5)
        self.assertIsNotNone(msg, "host did not forward the command")
        self.assertEqual(msg["type"], "send")
        self.assertEqual(msg["text"], "hello from coordinator")
        self.assertEqual(msg["nonce"], "nonce-1")

    def test_collect_dom_routes_read_only_command(self):
        self._append_inbox({"id": "cmd-dom", "type": "collect_dom",
                            "site": "chatgpt", "nonce": "dom-1",
                            "user_marker": "USER-TEST-MARKER",
                            "assistant_marker": "ASSISTANT-TEST-MARKER",
                            "auth": self.secret})
        message = read_msg(self.proc, timeout=1)
        self.assertIsNotNone(message, "host rejected the read-only collector")
        self.assertEqual(message["type"], "collect_dom")
        self.assertEqual(message["nonce"], "dom-1")
        self.assertNotIn("auth", message)

    def test_extension_to_coordinator_recorded(self):
        write_msg(self.proc, {"type": "send_result", "nonce": "nonce-9",
                              "ok": True, "origin": "https://chatgpt.com"})
        found = _wait_file_contains(
            self.outbox,
            lambda r: (r.get("direction") == "extension_to_coordinator"
                       and r.get("envelope", {}).get("type") == "send_result"
                       and r.get("envelope", {}).get("nonce") == "nonce-9"))
        self.assertTrue(found, "extension message was not recorded in outbox")

    def test_ping_round_trip(self):
        self._append_inbox({"id": "cmd-ping", "type": "ping",
                            "nonce": "ping-1", "auth": self.secret})
        msg = read_msg(self.proc, timeout=5)
        self.assertIsNotNone(msg, "ping was not forwarded to the extension")
        self.assertEqual(msg["type"], "ping")
        self.assertEqual(msg["nonce"], "ping-1")
        write_msg(self.proc, {"type": "pong", "nonce": "ping-1"})
        found = _wait_file_contains(
            self.outbox,
            lambda r: (r.get("direction") == "extension_to_coordinator"
                       and r.get("envelope", {}).get("type") == "pong"
                       and r.get("envelope", {}).get("nonce") == "ping-1"))
        self.assertTrue(found, "pong was not recorded in outbox")

    def test_bad_auth_refused(self):
        self._append_inbox({"id": "cmd-bad", "type": "send",
                            "site": "chatgpt", "text": "should not forward",
                            "nonce": "nonce-bad", "auth": "wrong-secret"})
        found = _wait_file_contains(
            self.outbox,
            lambda r: (r.get("direction") == "host_error"
                       and r.get("error") == "bad_auth"
                       and r.get("command_id") == "cmd-bad"))
        self.assertTrue(found, "bad-auth command was not refused")
        # Nothing should have been forwarded to the extension for it.
        self.assertIsNone(read_msg(self.proc, timeout=0.5),
                          "bad-auth command was forwarded to extension")

    def test_host_exits_on_stdin_close(self):
        self.proc.stdin.close()
        try:
            rc = self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.fail("host did not exit after stdin closed")
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
