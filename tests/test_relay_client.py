#!/usr/bin/env python3
"""RC2 tests for transport/relay_client.py against the local stub server.

Re-runs the 9 revised-protocol checks from TEST-RECORDS-v2.md §7
(health / next / reply / duplicate / get / codex refusal / empty /
missing token / flaky retry) plus a stub-log assertion that the duplicate
reply was never sent to the server.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
CLIENT = os.path.join(PKG, "transport", "relay_client.py")
STUB = os.path.join(PKG, "transport", "tests", "stub_server.py")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_port(port, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.1)
    return False


class StubServer:
    def __init__(self, tmp, flaky=False):
        self.port = _free_port()
        self.log = os.path.join(tmp, "stub.log")
        env = dict(os.environ)
        env["STUB_TOKEN"] = "test-token-123"
        env["STUB_LOG"] = self.log
        if flaky:
            env["STUB_FLAKY"] = "1"
        self.proc = subprocess.Popen(
            [sys.executable, STUB, str(self.port)],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        assert _wait_port(self.port), "stub server did not start"

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def log_records(self):
        try:
            with open(self.log, "r", encoding="utf-8") as f:
                return [json.loads(line) for line in f if line.strip()]
        except FileNotFoundError:
            return []


class TestRelayClient(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.stub = StubServer(self.tmp.name)
        self.env = dict(os.environ)
        self.env["PYTHONIOENCODING"] = "cp1252"
        self.env["AGENT_RELAY_BASE_URL"] = \
            f"http://127.0.0.1:{self.stub.port}"
        self.env["AGENT_RELAY_TOKEN"] = "test-token-123"
        self.env["AGENT_RELAY_STATE_FILE"] = os.path.join(
            self.tmp.name, "seen.json")

    def tearDown(self):
        self.stub.stop()
        self.tmp.cleanup()

    def _run(self, *args, env=None):
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", CLIENT, *args],
            env=env or self.env, capture_output=True, encoding="utf-8", timeout=30)
        return proc

    def test_full_sequence(self):
        # 1. health ok
        p = self._run("health")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('"status": "ok"', p.stdout)
        # 2. next returns the ChatGPT test message
        p = self._run("next")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("msg-test-001", p.stdout)
        self.assertIn('"sender": "chatgpt"', p.stdout)
        # 3. reply accepted
        reply_file = os.path.join(self.tmp.name, "reply.txt")
        with open(reply_file, "w", encoding="utf-8") as f:
            f.write("Muse: reliability first — every claim needs a run log.")
        p = self._run("reply", "--reply-to-message-id", "msg-test-001",
                      "--run-id", "RUN-1", "--reply-file", reply_file)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('"status": "accepted"', p.stdout)
        # 4. duplicate reply skipped client-side (server sees exactly 1 POST)
        p = self._run("reply", "--reply-to-message-id", "msg-test-001",
                      "--run-id", "RUN-1", "--reply-file", reply_file)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("duplicate_skipped", p.stdout)
        posts = [r for r in self.stub.log_records()
                 if r["method"] == "POST"
                 and r["path"] == "/v1/messages/reply"]
        self.assertEqual(len(posts), 1)
        # 5. next returns the codex message -> refused, exit 1
        p = self._run("next")
        self.assertEqual(p.returncode, 1)
        self.assertIn("untrusted_sender", p.stdout)
        # 6. next again -> empty (204)
        p = self._run("next")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('"status": "empty"', p.stdout)
        # 7. get works
        p = self._run("get", "--message-id", "msg-test-001")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("msg-test-001", p.stdout)

    def test_missing_token_clean_error(self):
        env = dict(self.env)
        env.pop("AGENT_RELAY_TOKEN", None)
        p = self._run("health", env=env)
        self.assertEqual(p.returncode, 2)
        self.assertIn("AGENT_RELAY_TOKEN is not set", p.stderr)

    def test_flaky_health_retries(self):
        flaky = StubServer(self.tmp.name, flaky=True)
        try:
            env = dict(self.env)
            env["AGENT_RELAY_BASE_URL"] = \
                f"http://127.0.0.1:{flaky.port}"
            p = self._run("health", env=env)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn('"attempts": 2', p.stdout)
        finally:
            flaky.stop()


if __name__ == "__main__":
    unittest.main()
