#!/usr/bin/env python3
"""Local stub of the Agent Relay HTTP interface, for client verification only.

Implements the agreed interface on 127.0.0.1 (never a public service):
    GET  /health
    GET  /v1/messages/next?recipient=muse
    POST /v1/messages/reply
    GET  /v1/messages/{message_id}

Behaviour (REVISED protocol, TASK-AGENT-RELAY-V06-MUSE-REVISED):
- Requires Authorization: Bearer <STUB_TOKEN> (default "test-token-123").
- /next returns the canned ChatGPT test message on the 1st call, then a
  sender=codex message on the 2nd call (must be refused by the client),
  then 204 empty.
- /reply expects sender=muse, recipient=chatgpt, reply_to_message_id,
  content, run_id; records the reply; a second reply for the same
  reply_to_message_id gets 409.
- With STUB_FLAKY=1 the first /health request returns 500 (retry test).
- Every request is appended to STUB_LOG as one JSON line (method, path,
  auth_present bool, status). The token value is NEVER logged.

Run:  STUB_LOG=/tmp/stub.log python3 stub_server.py 18765
Stop with Ctrl-C / kill.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

TOKEN = os.environ.get("STUB_TOKEN", "test-token-123")
LOG_PATH = os.environ.get("STUB_LOG", "/tmp/agent-relay-stub.log")
FLAKY = os.environ.get("STUB_FLAKY", "") == "1"

TEST_MESSAGE = {
    "discussion_id": "disc-test-001",
    "message_id": "msg-test-001",
    "sender": "chatgpt",
    "recipient": "muse",
    "content": "ChatGPT：我们正在设计一个免费、可靠的跨 AI 通信系统。请 Muse 用一句话提出最重要的可靠性建议。",
    "turn_number": 1,
    "source_session": "chatgpt-session-test-001",
}

# A message that must be REFUSED: Codex content must never be presented as
# ChatGPT's words. The client has to exit with untrusted_sender on this one.
CODEX_MESSAGE = {
    "discussion_id": "disc-test-001",
    "message_id": "msg-test-002",
    "sender": "codex",
    "recipient": "muse",
    "content": "Codex：这是开发侧的消息，不应被当作 ChatGPT 的发言。",
    "turn_number": 2,
    "source_session": "codex-session-test-001",
}

state = {
    "health_calls": 0,
    "next_calls": 0,
    "reply_calls": 0,
    "replies": {},  # reply_to_message_id -> body
    "messages": {TEST_MESSAGE["message_id"]: TEST_MESSAGE,
                 CODEX_MESSAGE["message_id"]: CODEX_MESSAGE},
}


def log_request(method, path, auth_present, status):
    line = json.dumps({
        "method": method, "path": path,
        "auth_present": auth_present, "status": status,
    }, ensure_ascii=False)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


class Handler(BaseHTTPRequestHandler):
    def _auth_ok(self):
        return self.headers.get("Authorization") == "Bearer " + TOKEN

    def _send_json(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
        log_request(self.command, self.path,
                    self.headers.get("Authorization") is not None, status)

    def _require_auth(self):
        if not self._auth_ok():
            self._send_json(401, {"error": "unauthorized"})
            return False
        return True

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            state["health_calls"] += 1
            if FLAKY and state["health_calls"] == 1:
                self._send_json(500, {"error": "flaky failure"})
                return
            self._send_json(200, {"status": "ok"})
            return
        if not self._require_auth():
            return
        if parsed.path == "/v1/messages/next":
            state["next_calls"] += 1
            qs = parse_qs(parsed.query)
            if qs.get("recipient", [""])[0] != "muse":
                self._send_json(400, {"error": "recipient must be muse"})
                return
            if state["next_calls"] == 1:
                self._send_json(200, TEST_MESSAGE)
            elif state["next_calls"] == 2:
                self._send_json(200, CODEX_MESSAGE)
            else:
                self.send_response(204)
                self.end_headers()
                log_request("GET", self.path, True, 204)
            return
        if parsed.path.startswith("/v1/messages/"):
            mid = parsed.path.split("/")[-1]
            msg = state["messages"].get(mid)
            if msg is None:
                self._send_json(404, {"error": "not found"})
            else:
                self._send_json(200, msg)
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/messages/reply":
            self._send_json(404, {"error": "not found"})
            return
        if not self._require_auth():
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError:
            self._send_json(400, {"error": "invalid json"})
            return
        state["reply_calls"] += 1
        mid = body.get("reply_to_message_id")
        if body.get("sender") != "muse" or body.get("recipient") != "chatgpt":
            self._send_json(400, {"error": "sender must be muse, "
                                           "recipient must be chatgpt"})
            return
        if mid in state["replies"]:
            self._send_json(409, {"error": "duplicate reply",
                                  "reply_to_message_id": mid})
            return
        state["replies"][mid] = body
        self._send_json(200, {"status": "accepted",
                              "reply_to_message_id": mid,
                              "run_id": body.get("run_id")})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18765
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"stub listening on 127.0.0.1:{port}", flush=True)
    server.serve_forever()
