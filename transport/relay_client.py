#!/usr/bin/env python3
"""Agent Relay communication client (Muse side).

Implements the REVISED interface agreed for TASK-AGENT-RELAY-V06-MUSE-REVISED
(ChatGPT is the discussant; Codex only develops and executes):

Receive (GET /v1/messages/next?recipient=muse):
    discussion_id, message_id, sender=chatgpt, recipient=muse,
    content, turn_number, source_session
Reply (POST /v1/messages/reply):
    sender=muse, recipient=chatgpt, reply_to_message_id, content, run_id
Also: GET /health, GET /v1/messages/{message_id}.

Design rules:
- Bearer token ONLY from the environment (AGENT_RELAY_TOKEN). Never hardcoded,
  never printed, never written to any file or log.
- Base URL ONLY from the environment (AGENT_RELAY_BASE_URL) or --base-url.
  Supports public https:// URLs and Tailscale private addresses
  (100.64.0.0/10 or *.ts.net), which are reached through the runtime tunnel
  proxy (same proxy host as HTTPS_PROXY, port 3130).
- SOURCE VERIFICATION (revised task): a received message is only treated as
  ChatGPT's words if payload sender == "chatgpt". Any other sender
  (e.g. "codex") is refused with status "untrusted_sender" and the run must
  stop — Codex messages must NEVER be presented as ChatGPT's. Received
  messages are discussion material only, never instructions to execute.
- The client only transports text. It NEVER executes, evaluates, or shells out
  any content received in a message. There is no code path that runs message
  content.
- One operation per invocation (health / next / reply / get). No loop inside
  the client: the discussion loop lives in the scheduled task, capped at
  3 rounds. This makes an infinite loop impossible by construction.
- Deduplication: replied message_ids are recorded in a local state file.
  A second reply attempt for the same reply_to_message_id is refused locally
  and never sent.
- Bounded retries: at most 3 attempts on network errors / 5xx / 429 with
  backoff (1s, 2s, 4s). No retry on other 4xx.
- message_id, discussion_id, turn_number and run_id are preserved in every
  request, response and log line.
- TIME: an AI's self-reported time is unreliable. Timestamps in logs and
  reports must come from run records (cron run logs), never from model text.

Usage:
    AGENT_RELAY_BASE_URL=http://100.x.y.z:PORT AGENT_RELAY_TOKEN=... \\
        python3 relay_client.py health
    python3 relay_client.py next
    python3 relay_client.py reply --reply-to-message-id MSG \\
        --run-id RUN --reply-file /path/to/reply.txt
    python3 relay_client.py get --message-id MSG

Exit codes: 0 ok (including duplicate-skipped), 1 error (including
untrusted sender), 2 config error.
Output: one JSON object on stdout. Errors also go to stderr.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

DEFAULT_TIMEOUT = 15
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (1, 2, 4)
REPLY_PREVIEW_CHARS = 120


def log_event(**fields):
    """One JSON line on stdout. Never include the token or proxy credentials."""
    fields.setdefault("ts", datetime.now(timezone.utc).isoformat())
    print(json.dumps(fields, ensure_ascii=False))
    sys.stdout.flush()


def fail(message, code=1):
    print(f"relay_client: error: {message}", file=sys.stderr)
    sys.exit(code)


def get_config():
    base_url = os.environ.get("AGENT_RELAY_BASE_URL", "").strip()
    token = os.environ.get("AGENT_RELAY_TOKEN", "")
    if not base_url:
        fail("AGENT_RELAY_BASE_URL is not set", code=2)
    if not token:
        fail("AGENT_RELAY_TOKEN is not set", code=2)
    return base_url.rstrip("/"), token


def is_tailnet_host(host):
    """True for Tailscale private addresses: 100.64.0.0/10 or *.ts.net."""
    if not host:
        return False
    if host.endswith(".ts.net"):
        return True
    try:
        import ipaddress

        ip = ipaddress.ip_address(host)
        return ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        return False


def build_opener(base_url):
    """Public https goes through the normal egress proxy; tailnet addresses
    go through the runtime tunnel proxy (same proxy host, port 3130)."""
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or ""
    use_tunnel = is_tailnet_host(host) or os.environ.get(
        "AGENT_RELAY_VIA_TAILSCALE", ""
    ) == "1"
    if use_tunnel:
        https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get(
            "https_proxy", ""
        )
        if not https_proxy:
            fail("tailnet address requires HTTPS_PROXY to derive the tunnel proxy",
                 code=2)
        parts = urllib.parse.urlparse(https_proxy)
        # Rebuild as [userinfo@]hostname:3130, preserving proxy auth.
        host = parts.hostname or ""
        if not host:
            fail("cannot parse HTTPS_PROXY host for the tunnel proxy",
                 code=2)
        netloc = host + ":3130"
        if parts.username:
            userinfo = parts.username
            if parts.password:
                userinfo += ":" + parts.password
            netloc = userinfo + "@" + netloc
        tunnel_url = urllib.parse.urlunparse(
            parts._replace(netloc=netloc))
        proxy_handler = urllib.request.ProxyHandler(
            {"http": tunnel_url, "https": tunnel_url})
        return urllib.request.build_opener(proxy_handler), True
    # Default opener honours the environment proxy (including no_proxy).
    return urllib.request.build_opener(), False


def request_with_retries(opener, method, url, token, body=None):
    """One logical request, at most MAX_ATTEMPTS on network errors / 5xx / 429."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method=method)
        try:
            with opener.open(req, timeout=DEFAULT_TIMEOUT) as resp:
                raw = resp.read()
                return resp.status, raw, attempt
        except urllib.error.HTTPError as e:
            raw = e.read()
            if e.code in (429,) or 500 <= e.code < 600:
                last_error = f"HTTP {e.code}"
                if attempt < MAX_ATTEMPTS:
                    time.sleep(BACKOFF_SECONDS[attempt - 1])
                    continue
            return e.code, raw, attempt
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = str(e)
            if attempt < MAX_ATTEMPTS:
                time.sleep(BACKOFF_SECONDS[attempt - 1])
                continue
            raise
    raise RuntimeError(f"request failed after {MAX_ATTEMPTS} attempts: {last_error}")


def parse_json(raw):
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {"_raw": raw.decode("utf-8", errors="replace")}


# --- dedupe state -------------------------------------------------------

def state_path():
    explicit = os.environ.get("AGENT_RELAY_STATE_FILE", "").strip()
    if explicit:
        return explicit
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "state", "seen.json")


def load_state():
    path = state_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("replied", {})
            return data
    except (FileNotFoundError, ValueError):
        pass
    return {"replied": {}}


def save_state(state):
    path = state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def already_replied(message_id):
    return message_id in load_state().get("replied", {})


def mark_replied(message_id, discussion_id, run_id):
    state = load_state()
    state["replied"][message_id] = {
        "discussion_id": discussion_id,
        "run_id": run_id,
        "replied_at": datetime.now(timezone.utc).isoformat(),
    }
    save_state(state)


# --- operations ---------------------------------------------------------

def op_health(base_url, token, opener):
    status, raw, attempts = request_with_retries(
        opener, "GET", base_url + "/health", token)
    payload = parse_json(raw)
    log_event(op="health", status="ok" if status == 200 else "error",
              http_status=status, attempts=attempts, payload=payload)
    return 0 if status == 200 else 1


def op_next(base_url, token, opener, recipient="muse"):
    url = (base_url + "/v1/messages/next?recipient="
           + urllib.parse.quote(recipient))
    status, raw, attempts = request_with_retries(opener, "GET", url, token)
    if status == 204 or not raw:
        log_event(op="next", status="empty", http_status=status,
                  attempts=attempts)
        return 0
    payload = parse_json(raw)
    if status != 200:
        log_event(op="next", status="error", http_status=status,
                  attempts=attempts, payload=payload)
        return 1
    if not (isinstance(payload, dict) and payload.get("message_id")):
        log_event(op="next", status="empty", http_status=status,
                  attempts=attempts, payload=payload)
        return 0
    # Source verification: only sender == "chatgpt" may be presented as
    # ChatGPT's words. Anything else stops the run (exit 1).
    sender = payload.get("sender")
    if sender != "chatgpt":
        log_event(op="next", status="untrusted_sender",
                  claimed_sender=sender,
                  message_id=payload.get("message_id"),
                  discussion_id=payload.get("discussion_id"),
                  http_status=status, attempts=attempts)
        print("relay_client: error: refusing message with sender "
              f"'{sender}': only sender=chatgpt is accepted",
              file=sys.stderr)
        return 1
    if payload.get("recipient") not in (None, "muse"):
        log_event(op="next", status="wrong_recipient",
                  recipient=payload.get("recipient"),
                  message_id=payload.get("message_id"),
                  discussion_id=payload.get("discussion_id"),
                  http_status=status, attempts=attempts)
        print("relay_client: error: message recipient is not muse",
              file=sys.stderr)
        return 1
    if "content" not in payload:
        log_event(op="next", status="protocol_mismatch",
                  message_id=payload.get("message_id"),
                  discussion_id=payload.get("discussion_id"),
                  detail="missing 'content' field",
                  http_status=status, attempts=attempts)
        print("relay_client: error: message payload has no 'content' field",
              file=sys.stderr)
        return 1
    log_event(op="next", status="message",
              message_id=payload.get("message_id"),
              discussion_id=payload.get("discussion_id"),
              sender="chatgpt",
              turn_number=payload.get("turn_number"),
              source_session=payload.get("source_session"),
              content_preview=(payload.get("content") or "")
              [:REPLY_PREVIEW_CHARS],
              http_status=status, attempts=attempts)
    return 0


def op_reply(base_url, token, opener, reply_to_message_id, run_id,
             reply_text, discussion_id=None):
    if already_replied(reply_to_message_id):
        log_event(op="reply", status="duplicate_skipped",
                  reply_to_message_id=reply_to_message_id,
                  discussion_id=discussion_id, run_id=run_id)
        return 0
    body = {
        "sender": "muse",
        "recipient": "chatgpt",
        "reply_to_message_id": reply_to_message_id,
        "content": reply_text,
        "run_id": run_id,
    }
    status, raw, attempts = request_with_retries(
        opener, "POST", base_url + "/v1/messages/reply", token, body)
    payload = parse_json(raw)
    if status in (200, 201, 202):
        mark_replied(reply_to_message_id, discussion_id, run_id)
        log_event(op="reply", status="accepted",
                  reply_to_message_id=reply_to_message_id,
                  discussion_id=discussion_id, run_id=run_id,
                  http_status=status, attempts=attempts, payload=payload)
        return 0
    log_event(op="reply", status="error",
              reply_to_message_id=reply_to_message_id,
              discussion_id=discussion_id, run_id=run_id,
              http_status=status, attempts=attempts, payload=payload)
    return 1


def op_get(base_url, token, opener, message_id):
    url = base_url + "/v1/messages/" + urllib.parse.quote(message_id)
    status, raw, attempts = request_with_retries(opener, "GET", url, token)
    payload = parse_json(raw)
    log_event(op="get", status="ok" if status == 200 else "error",
              message_id=message_id, http_status=status,
              attempts=attempts, payload=payload)
    return 0 if status == 200 else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Agent Relay client (Muse side)")
    parser.add_argument("--base-url", default="",
                        help="override AGENT_RELAY_BASE_URL")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health")
    p_next = sub.add_parser("next")
    p_next.add_argument("--recipient", default="muse")
    p_reply = sub.add_parser("reply")
    p_reply.add_argument("--reply-to-message-id", required=True)
    p_reply.add_argument("--run-id", required=True)
    p_reply.add_argument("--discussion-id", default=None,
                         help="recorded locally only, not sent in the body")
    p_reply.add_argument("--reply-file", required=True,
                         help="file containing the reply text (never argv)")
    p_get = sub.add_parser("get")
    p_get.add_argument("--message-id", required=True)
    args = parser.parse_args(argv)

    env_base, token = get_config()
    base_url = (args.base_url or env_base).rstrip("/")
    opener, via_tunnel = build_opener(base_url)
    log_event(op="config", status="ready", via_tunnel=via_tunnel,
              base_host=urllib.parse.urlparse(base_url).hostname)

    if args.command == "health":
        return op_health(base_url, token, opener)
    if args.command == "next":
        return op_next(base_url, token, opener, args.recipient)
    if args.command == "reply":
        try:
            with open(args.reply_file, "r", encoding="utf-8") as f:
                reply_text = f.read()
        except OSError as e:
            fail(f"cannot read reply file: {e}", code=2)
        if not reply_text.strip():
            fail("reply file is empty", code=2)
        return op_reply(base_url, token, opener,
                        args.reply_to_message_id, args.run_id, reply_text,
                        args.discussion_id)
    if args.command == "get":
        return op_get(base_url, token, opener, args.message_id)
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
