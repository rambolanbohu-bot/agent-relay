#!/usr/bin/env python3
"""Agent Relay Skill v1.0.0-rc4 — Windows E2E protocol driver.

Drives the REAL Native Messaging host (agent-relay-host.exe on
Windows, or python native_host.py for a Linux pre-flight) through
the length-prefixed JSON protocol and verifies, per segment:

  1. coordinator -> host -> extension: a `ping` command written to
     inbox.jsonl is forwarded to stdout with the same nonce;
  2. extension -> host -> coordinator record: an envelope written to
     the host's stdin is recorded in outbox.jsonl with the same
     message_id (and a `pong` reply to a ping completes the loop);
  3. message ID / ACK: a `send` command is forwarded with its id and
     message_id intact;
  4. error handling: wrong auth -> host_error bad_auth; malformed
     inbox line -> host_error bad_inbox_json; unknown command type ->
     host_error unknown_command_type:*;
  5. timeout behaviour: every expected reply is awaited with a
     deadline (default 5 s); a missing reply is recorded as TIMEOUT,
     never silently skipped. Round-trip latency is measured.

This driver plays the extension side over pipes (it is NOT real
Chrome). The real-Chrome segments (extension load, tab
communication, no-focus check) are manual steps in
windows_e2e_test/README.md and are recorded in the record template.
Nothing here simulates the Windows round trip and calls it a pass:
the record states exactly which host binary was used.

Stdout is read by ONE persistent reader thread (select() does not
work on pipes on Windows, so a per-read select would be wrong there).

Usage (Windows, against the real .exe):
    python windows_e2e_test\\native_host_driver.py ^
        --exe <temp-install>\\agent-relay-skill\\transport\\agent-relay-host.exe ^
        --record <temp>\\e2e-record-driver.json
Usage (Linux pre-flight, same protocol, python host):
    python3 windows_e2e_test/native_host_driver.py \
        --python-host transport/native_host.py \
        --state-dir /tmp/nh-state --record /tmp/record.json

Exit code: 0 only when every step passes.
"""

import argparse
import json
import os
import queue
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

DEFAULT_TIMEOUT = 5.0


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _read_msg_blocking(stream):
    """Read one length-prefixed JSON message (blocking). Returns the
    decoded object, or None on EOF."""
    header = stream.read(4)
    if not header:
        return None
    if len(header) < 4:
        raise ValueError("truncated native message header")
    (length,) = struct.unpack("<I", header)
    if length > 10 * 1024 * 1024:
        raise ValueError("native message too large: %d" % length)
    raw = stream.read(length)
    if len(raw) < length:
        raise ValueError("truncated native message body")
    return json.loads(raw.decode("utf-8"))


def _write_msg(stream, obj):
    raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    stream.write(struct.pack("<I", len(raw)))
    stream.write(raw)
    stream.flush()


class _StdoutReader(threading.Thread):
    """One persistent reader for the host's stdout (a per-read select
    would not work on Windows pipes, and a second reader thread could
    steal messages)."""

    def __init__(self, stream):
        super().__init__(daemon=True)
        self.stream = stream
        self.queue = queue.Queue()

    def run(self):
        try:
            while True:
                msg = _read_msg_blocking(self.stream)
                if msg is None:
                    self.queue.put(("eof", None))
                    return
                self.queue.put(("msg", msg))
        except Exception as e:  # noqa: BLE001 - surfaced to the driver
            self.queue.put(("error", str(e)))

    def next(self, timeout):
        """Next message, or None on timeout / EOF. Raises ValueError
        on a malformed message."""
        try:
            kind, value = self.queue.get(timeout=timeout)
        except queue.Empty:
            return None
        if kind == "error":
            raise ValueError(value)
        return value  # ("msg", obj) -> obj; ("eof", None) -> None


class Driver:
    def __init__(self, host_cmd, state_dir, timeout=DEFAULT_TIMEOUT):
        self.host_cmd = host_cmd
        self.state_dir = state_dir
        self.timeout = timeout
        self.proc = None
        self.reader = None
        self.steps = []
        self.secret = None

    def _step(self, name, result, detail="", latency_ms=None):
        self.steps.append({"name": name, "result": result,
                           "detail": detail, "latency_ms": latency_ms,
                           "at": _utcnow()})
        print("[%s] %s %s" % (result, name, detail), flush=True)

    def _wait_secret(self):
        path = os.path.join(self.state_dir, "secret")
        deadline = time.time() + 10
        while time.time() < deadline:
            if os.path.exists(path):
                with open(path, "r", encoding="ascii") as f:
                    return f.read().strip()
            time.sleep(0.2)
        return None

    def _append_inbox(self, obj):
        path = os.path.join(self.state_dir, "inbox.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def _append_inbox_raw(self, line):
        path = os.path.join(self.state_dir, "inbox.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _outbox_records(self):
        path = os.path.join(self.state_dir, "outbox.jsonl")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return [json.loads(line) for line in f if line.strip()]
        except (OSError, ValueError):
            return []

    def _wait_outbox(self, predicate, timeout=None):
        deadline = time.time() + (timeout or self.timeout)
        while time.time() < deadline:
            for rec in self._outbox_records():
                if predicate(rec):
                    return rec
            time.sleep(0.2)
        return None

    def _read_forwarded(self, step_name):
        """Read the next forwarded message from the host's stdout.
        Returns (msg, error_string); msg is None on timeout/EOF."""
        try:
            return self.reader.next(self.timeout), None
        except ValueError as e:
            return None, str(e)

    def run(self):
        started = _utcnow()
        self.proc = subprocess.Popen(
            self.host_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        self.reader = _StdoutReader(self.proc.stdout)
        self.reader.start()
        self.secret = self._wait_secret()
        if not self.secret:
            self._step("host_start_and_secret", "FAIL",
                       "secret file did not appear in 10s")
            return self._finish(started)
        self._step("host_start_and_secret", "PASS",
                   "host started, secret file present")

        # 1. ping: coordinator -> host -> extension (stdout).
        t0 = time.time()
        self._append_inbox({"id": "e2e-ping-1", "type": "ping",
                            "nonce": "n-ping-1", "auth": self.secret})
        msg, err = self._read_forwarded("ping_forward")
        if err is not None:
            self._step("ping_forward", "FAIL", "bad message: %s" % err)
        elif msg is None:
            self._step("ping_forward", "TIMEOUT",
                       "no forwarded ping within %.0fs" % self.timeout)
        else:
            ok = (msg.get("type") == "ping"
                  and msg.get("nonce") == "n-ping-1")
            self._step("ping_forward",
                       "PASS" if ok else "FAIL",
                       "forwarded: %s" % json.dumps(msg, ensure_ascii=False),
                       latency_ms=int((time.time() - t0) * 1000))

        # 2. pong: extension -> host -> coordinator record (outbox).
        _write_msg(self.proc.stdin, {"type": "pong", "nonce": "n-ping-1"})
        rec = self._wait_outbox(
            lambda r: r.get("direction") == "extension_to_coordinator"
            and (r.get("envelope") or {}).get("type") == "pong"
            and (r.get("envelope") or {}).get("nonce") == "n-ping-1")
        self._step("pong_recorded", "PASS" if rec else "TIMEOUT",
                   "outbox record found" if rec else
                   "no pong record within %.0fs" % self.timeout)

        # 3. send: message id / ACK — the forwarded envelope keeps id
        #    and message_id intact.
        t0 = time.time()
        self._append_inbox({"id": "e2e-send-1", "type": "send",
                            "message_id": "msg-e2e-1",
                            "content": "E2E test message",
                            "auth": self.secret})
        msg, err = self._read_forwarded("send_forward_id")
        if err is not None:
            self._step("send_forward_id", "FAIL", "bad message: %s" % err)
        elif msg is None:
            self._step("send_forward_id", "TIMEOUT",
                       "no forwarded send within %.0fs" % self.timeout)
        else:
            ok = (msg.get("id") == "e2e-send-1"
                  and msg.get("message_id") == "msg-e2e-1")
            self._step("send_forward_id",
                       "PASS" if ok else "FAIL",
                       "forwarded: %s" % json.dumps(msg, ensure_ascii=False),
                       latency_ms=int((time.time() - t0) * 1000))

        # 4a. wrong auth -> host_error bad_auth with the command id.
        self._append_inbox({"id": "e2e-bad-auth", "type": "ping",
                            "nonce": "n-bad", "auth": "wrong-secret"})
        rec = self._wait_outbox(
            lambda r: r.get("direction") == "host_error"
            and r.get("error") == "bad_auth"
            and r.get("command_id") == "e2e-bad-auth")
        self._step("error_bad_auth", "PASS" if rec else "TIMEOUT",
                   "bad_auth recorded" if rec else
                   "no bad_auth record within %.0fs" % self.timeout)

        # 4b. malformed inbox line -> host_error bad_inbox_json.
        self._append_inbox_raw("{this is not json")
        rec = self._wait_outbox(
            lambda r: r.get("direction") == "host_error"
            and r.get("error") == "bad_inbox_json")
        self._step("error_bad_inbox_json", "PASS" if rec else "TIMEOUT",
                   "bad_inbox_json recorded" if rec else
                   "no bad_inbox_json record within %.0fs" % self.timeout)

        # 4c. unknown command type -> host_error unknown_command_type.
        self._append_inbox({"id": "e2e-bogus", "type": "bogus",
                            "auth": self.secret})
        rec = self._wait_outbox(
            lambda r: r.get("direction") == "host_error"
            and str(r.get("error", "")).startswith(
                "unknown_command_type")
            and r.get("command_id") == "e2e-bogus")
        self._step("error_unknown_command", "PASS" if rec else "TIMEOUT",
                   "unknown_command_type recorded" if rec else
                   "no unknown_command_type record within %.0fs"
                   % self.timeout)

        # 5. shutdown: the host exits cleanly on the shutdown envelope.
        try:
            _write_msg(self.proc.stdin, {"type": "shutdown"})
        except (BrokenPipeError, OSError):
            pass
        try:
            self.proc.wait(timeout=5)
            self._step("shutdown_clean_exit",
                       "PASS" if self.proc.returncode == 0 else "FAIL",
                       "exit code %s" % self.proc.returncode)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self._step("shutdown_clean_exit", "TIMEOUT",
                       "host did not exit within 5s after shutdown")
        return self._finish(started)

    def _finish(self, started):
        overall = "PASS" if all(
            s["result"] == "PASS" for s in self.steps) else "FAIL"
        record = {"driver": "native_host_driver.py",
                  "host_cmd": [str(c) for c in self.host_cmd],
                  "state_dir": self.state_dir,
                  "started_at": started,
                  "finished_at": _utcnow(),
                  "overall": overall,
                  "steps": self.steps}
        return overall, record


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Agent Relay Windows E2E protocol driver")
    parser.add_argument("--exe", default=None,
                        help="path to agent-relay-host.exe (Windows)")
    parser.add_argument("--python-host", default=None,
                        help="path to native_host.py (Linux pre-flight)")
    parser.add_argument("--state-dir", default=None,
                        help="state dir (required with --python-host)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--record", default=None,
                        help="write the JSON record to this file")
    args = parser.parse_args(argv)

    if args.exe:
        # The .exe derives its state dir from its own location:
        # <skill>/transport/agent-relay-host.exe ->
        # <skill>/orchestrator/state/native_host
        skill_root = os.path.dirname(os.path.dirname(
            os.path.abspath(args.exe)))
        state_dir = os.path.join(skill_root, "orchestrator", "state",
                                 "native_host")
        host_cmd = [os.path.abspath(args.exe)]
    elif args.python_host:
        if not args.state_dir:
            print("native_host_driver: --state-dir is required with "
                  "--python-host", file=sys.stderr)
            return 2
        state_dir = os.path.abspath(args.state_dir)
        host_cmd = [sys.executable, os.path.abspath(args.python_host),
                    "--state-dir", state_dir]
    else:
        print("native_host_driver: give --exe or --python-host",
              file=sys.stderr)
        return 2

    os.makedirs(state_dir, exist_ok=True)
    driver = Driver(host_cmd, state_dir, timeout=args.timeout)
    overall, record = driver.run()
    text = json.dumps(record, ensure_ascii=False, indent=2)
    if args.record:
        with open(args.record, "w", encoding="utf-8") as f:
            f.write(text)
        print("\nRecord written to: %s" % args.record)
    print("\nOVERALL: %s" % overall)
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
