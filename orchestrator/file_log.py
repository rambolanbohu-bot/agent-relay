#!/usr/bin/env python3
"""Agent Relay Skill v1.0.0-rc2 — 单写入者文件日志（v1 默认权威状态来源）.

RC2 改动（ChatGPT 审查 P1-3、Security-1）：
- 严格去重：message_id 在 kind="message" 的记录里唯一；nonce 在所有
  带 nonce 的记录里唯一。重复写入直接拒绝（退出码 1），绝不写两遍。
- 发送事务：发消息分三步写盘——先写 send_intent（想发），发完写
  send_success（已发）或 send_failed（没发出去）。绝不在“不知道
  发没发出去”的状态下猜。
- 重启对账（reconcile）：对账时对每个“有 intent、无结果”的 message_id
  去接收方核实：确认已收到 → 补 send_success；确认未收到 →
  补 send_failed（可重试）；核实不了 → 标记 send_uncertain（UNCERTAIN）
  并停下，绝不自动重发（条件 4：保守恢复）。
- 锁：改用 orchestrator/locking.py 的操作系统锁。RC1 的“锁文件超过
  60 秒就删掉”已删除——删锁可能删掉一个活着的写入者的锁（Security-1）。
  锁文件永不删除；进程死掉时操作系统自动释放锁。

为什么先用文件日志而不是 SQLite：
  云电脑 SQLite 只有在文件持久化、重启恢复、并发写入三项验证通过后，
  才能成为权威来源；验证未通过之前，权威来源是这份单写入者 JSONL 日志。
  （见 docs/KNOWN-LIMITATIONS.md）

规则：
- 只追加，不修改、不删除已写记录。旧记录永远保留（审计用）。
- 同一时间只有一个写入者：用操作系统排他锁保护；拿不到锁时等待重试，
  超时则报错退出，绝不两个写入者同时写。
- 每条记录带 seq（单调递增）、UTC 时间戳；含 content 的记录带
  content_sha256 与 content_len；content 超过 8000 字拒绝写入。
- 每次追加后 fsync，保证落盘。
- 本脚本只做状态记录，不推理、不发消息、不执行任何讨论内容。

用法：
    python3 file_log.py append --log state/discussion.jsonl \
        --record-file /path/to/record.json
    python3 file_log.py send-intent --log state/discussion.jsonl \
        --project-id P-001 --message-id m-001 --nonce n-001 \
        --content-hash <sha256> --content-len 123
    python3 file_log.py send-confirm --log state/discussion.jsonl \
        --message-id m-001 --outcome sent|failed
    python3 file_log.py mark-uncertain --log state/discussion.jsonl \
        --message-id m-001 --reason "receiver unreachable"
    python3 file_log.py reconcile --log state/discussion.jsonl \
        [--verify-cmd "python3 verify.py {message_id}"]
    python3 file_log.py uncertain --log state/discussion.jsonl
    python3 file_log.py last --log state/discussion.jsonl
    python3 file_log.py verify --log state/discussion.jsonl
    python3 file_log.py count --log state/discussion.jsonl

record.json 示例：
    {"project_id": "P-001", "kind": "message", "message_id": "m-001",
     "nonce": "n-001", "sender": "muse", "turn_number": 1,
     "content": "...", "status": "sent"}
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

# locking.py lives next to this file.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from locking import FileLock, lock_path_for  # noqa: E402

MAX_CONTENT_CHARS = 8000
LOCK_TIMEOUT_SECONDS = 10


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _content_hash(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def read_records(log_path):
    records = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
    except FileNotFoundError:
        return []
    return records


def _check_dedup(records, record):
    """Strict dedup (P1-3). Raises ValueError on a duplicate.

    - message_id is unique among kind="message" records.
    - nonce is unique among all records that carry one.
    - a send_intent for a message_id is allowed only once; a send_success /
      send_failed / send_uncertain for a message_id is allowed only once and
      only after a send_intent for it.
    """
    kind = record.get("kind", "message")
    mid = record.get("message_id")
    nonce = record.get("nonce")
    for rec in records:
        if nonce is not None and rec.get("nonce") == nonce:
            raise ValueError(
                f"duplicate nonce: {nonce!r} (already in seq {rec.get('seq')})")
        if kind == "message" and rec.get("kind") == "message" \
                and mid is not None and rec.get("message_id") == mid:
            raise ValueError(
                f"duplicate message_id: {mid!r} "
                f"(already in seq {rec.get('seq')})")
    if kind == "send_intent":
        for rec in records:
            if rec.get("kind") == "send_intent" \
                    and rec.get("message_id") == mid:
                raise ValueError(
                    f"duplicate send_intent for message_id: {mid!r}")
    if kind in ("send_success", "send_failed", "send_uncertain"):
        intents = [r for r in records
                   if r.get("kind") == "send_intent"
                   and r.get("message_id") == mid]
        if not intents:
            raise ValueError(
                f"cannot record {kind} for {mid!r}: no send_intent on file")
        for rec in records:
            if rec.get("kind") in ("send_success", "send_failed",
                                   "send_uncertain") \
                    and rec.get("message_id") == mid:
                raise ValueError(
                    f"send outcome for {mid!r} already recorded "
                    f"(seq {rec.get('seq')}, kind {rec.get('kind')})")
    if kind == "send_reconciled":
        # HOTFIX 5 (P2, ATTEMPT-08): a late receipt may upgrade an
        # UNCERTAIN transaction to delivered-late (or failed) AFTER
        # the outcome was already recorded. The one-outcome rule
        # above forbids a second send_success / send_failed /
        # send_uncertain for the same message_id, so the upgrade
        # is recorded as a separate kind. It is allowed ONLY after
        # a send_uncertain (never after a terminal send_success /
        # send_failed — those are final), and only once per
        # message_id. This keeps the audit trail complete (the
        # original uncertain outcome stands as history) while
        # making the reconciliation itself durable and queryable.
        intents = [r for r in records
                   if r.get("kind") == "send_intent"
                   and r.get("message_id") == mid]
        if not intents:
            raise ValueError(
                f"cannot record send_reconciled for {mid!r}: "
                "no send_intent on file")
        uncertain = [r for r in records
                     if r.get("kind") == "send_uncertain"
                     and r.get("message_id") == mid]
        if not uncertain:
            raise ValueError(
                f"cannot record send_reconciled for {mid!r}: "
                "no send_uncertain on file (only an UNCERTAIN "
                "transaction can be reconciled)")
        for rec in records:
            if rec.get("kind") == "send_reconciled" \
                    and rec.get("message_id") == mid:
                raise ValueError(
                    f"send_reconciled for {mid!r} already recorded "
                    f"(seq {rec.get('seq')})")


def append_record(log_path, record):
    """Append one record (dedup-checked, locked, fsynced)."""
    if not isinstance(record, dict):
        raise ValueError("record must be a JSON object")
    content = record.get("content")
    if content is not None:
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        if len(content) > MAX_CONTENT_CHARS:
            raise ValueError(
                f"content too long: {len(content)} chars, max {MAX_CONTENT_CHARS}")
        record["content_sha256"] = _content_hash(content)
        record["content_len"] = len(content)
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    with FileLock(lock_path_for(log_path), timeout=LOCK_TIMEOUT_SECONDS):
        records = read_records(log_path)
        _check_dedup(records, record)
        record["seq"] = (records[-1]["seq"] + 1) if records else 1
        record["ts"] = _utcnow()
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
    return record


def send_intent(log_path, project_id, message_id, nonce,
                content_hash=None, content_len=None):
    """Step 1 of the send transaction: record the intent BEFORE sending."""
    if not message_id or not nonce:
        raise ValueError("send_intent requires message_id and nonce")
    record = {
        "kind": "send_intent",
        "project_id": project_id,
        "message_id": message_id,
        "nonce": nonce,
        "status": "intent",
    }
    if content_hash is not None:
        record["content_sha256"] = content_hash
    if content_len is not None:
        record["content_len"] = content_len
    return append_record(log_path, record)


def send_confirm(log_path, message_id, outcome):
    """Step 2 of the send transaction: record the result AFTER sending.

    outcome: "sent" (receiver confirmed) or "failed" (definitely not sent).
    A result that cannot be confirmed is NOT a confirm — use
    mark_uncertain() instead (condition 4).
    """
    if outcome not in ("sent", "failed"):
        raise ValueError("outcome must be 'sent' or 'failed'")
    record = {
        "kind": "send_success" if outcome == "sent" else "send_failed",
        "message_id": message_id,
        "status": outcome,
    }
    return append_record(log_path, record)


def mark_uncertain(log_path, message_id, reason=""):
    """Mark a send UNCERTAIN: it may have gone through, we cannot verify.

    After this, run.py must PAUSE the project — never auto-resend.
    """
    record = {
        "kind": "send_uncertain",
        "message_id": message_id,
        "status": "uncertain",
        "reason": reason,
    }
    return append_record(log_path, record)


def send_reconciled(log_path, message_id, outcome, reason="",
                    evidence=None):
    """Record a late-receipt reconciliation (HOTFIX 5, P2).

    outcome: "sent" (a late receipt proved delivery) or "failed"
    (a late receipt proved it was definitely not sent). This is
    the ONLY way to change an UNCERTAIN transaction's status after
    its outcome was recorded: the one-outcome rule forbids a second
    send_success / send_failed / send_uncertain, so the upgrade is
    a separate kind, allowed only after a send_uncertain and only
    once per message_id (enforced by _check_dedup). The original
    send_uncertain record stands as history; this record is the
    durable audit trail of the reconciliation, with the receipt
    evidence and the reason. It NEVER triggers a re-send.
    """
    if outcome not in ("sent", "failed"):
        raise ValueError("outcome must be 'sent' or 'failed'")
    record = {
        "kind": "send_reconciled",
        "message_id": message_id,
        "status": outcome,
        "reason": reason,
    }
    if evidence is not None:
        record["evidence"] = evidence
    return append_record(log_path, record)


def pending_intents(log_path):
    """message_ids with a send_intent but no outcome record yet."""
    records = read_records(log_path)
    intents = {}
    settled = set()
    for rec in records:
        kind = rec.get("kind")
        mid = rec.get("message_id")
        if kind == "send_intent" and mid:
            intents[mid] = rec
        elif kind in ("send_success", "send_failed", "send_uncertain") and mid:
            settled.add(mid)
    return [mid for mid in intents if mid not in settled]


def list_uncertain(log_path):
    records = read_records(log_path)
    return [rec for rec in records if rec.get("kind") == "send_uncertain"]


def reconcile(log_path, verify_fn=None):
    """Reconcile pending intents after a restart (condition 4).

    verify_fn(message_id) must return one of:
      "sent"     — the receiver confirms it has the message
      "not_sent" — the receiver confirms it does NOT have it
      "unknown"  — cannot verify (no connection / receiver cannot confirm)
    If verify_fn is None, every pending intent is marked UNCERTAIN
    (the safe default: never guess, never auto-resend).

    Returns {"reconciled": [...], "uncertain": [...]}.
    """
    result = {"reconciled": [], "uncertain": []}
    for mid in pending_intents(log_path):
        verdict = "unknown"
        if verify_fn is not None:
            try:
                verdict = verify_fn(mid)
            except Exception:
                verdict = "unknown"
        if verdict == "sent":
            send_confirm(log_path, mid, "sent")
            result["reconciled"].append({"message_id": mid,
                                         "verdict": "sent"})
        elif verdict == "not_sent":
            send_confirm(log_path, mid, "failed")
            result["reconciled"].append({"message_id": mid,
                                         "verdict": "not_sent"})
        else:
            mark_uncertain(log_path, mid,
                           reason="could not verify with receiver on restart")
            result["uncertain"].append(mid)
    return result


def verify_log(log_path):
    """Recompute hashes; report corrupt / out-of-order / duplicate records."""
    records = read_records(log_path)
    problems = []
    prev_seq = 0
    seen_message_ids = set()
    seen_nonces = set()
    for rec in records:
        if rec.get("seq") != prev_seq + 1:
            problems.append(
                {"seq": rec.get("seq"), "problem": "seq_not_monotonic"})
        prev_seq = rec.get("seq", prev_seq)
        content = rec.get("content")
        if content is not None:
            if rec.get("content_sha256") != _content_hash(content):
                problems.append(
                    {"seq": rec.get("seq"), "problem": "hash_mismatch"})
            if rec.get("content_len") != len(content):
                problems.append(
                    {"seq": rec.get("seq"), "problem": "length_mismatch"})
        if rec.get("kind") == "message" and rec.get("message_id"):
            if rec["message_id"] in seen_message_ids:
                problems.append({"seq": rec.get("seq"),
                                 "problem": "duplicate_message_id"})
            seen_message_ids.add(rec["message_id"])
        if rec.get("nonce"):
            if rec["nonce"] in seen_nonces:
                problems.append({"seq": rec.get("seq"),
                                 "problem": "duplicate_nonce"})
            seen_nonces.add(rec["nonce"])
    return {"records": len(records), "problems": problems,
            "ok": len(problems) == 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Agent Relay state file log")
    sub = parser.add_subparsers(dest="command", required=True)
    p_append = sub.add_parser("append")
    p_append.add_argument("--log", required=True)
    p_append.add_argument("--record-file", required=True)
    p_intent = sub.add_parser("send-intent")
    p_intent.add_argument("--log", required=True)
    p_intent.add_argument("--project-id", default="")
    p_intent.add_argument("--message-id", required=True)
    p_intent.add_argument("--nonce", required=True)
    p_intent.add_argument("--content-hash", default=None)
    p_intent.add_argument("--content-len", type=int, default=None)
    p_confirm = sub.add_parser("send-confirm")
    p_confirm.add_argument("--log", required=True)
    p_confirm.add_argument("--message-id", required=True)
    p_confirm.add_argument("--outcome", required=True,
                           choices=["sent", "failed"])
    p_unc = sub.add_parser("mark-uncertain")
    p_unc.add_argument("--log", required=True)
    p_unc.add_argument("--message-id", required=True)
    p_unc.add_argument("--reason", default="")
    p_rec = sub.add_parser("reconcile")
    p_rec.add_argument("--log", required=True)
    p_rec.add_argument("--verify-cmd", default=None,
                       help="command run as: <cmd> {message_id}; must print "
                            "sent / not_sent / unknown on stdout")
    p_unclist = sub.add_parser("uncertain")
    p_unclist.add_argument("--log", required=True)
    p_last = sub.add_parser("last")
    p_last.add_argument("--log", required=True)
    p_verify = sub.add_parser("verify")
    p_verify.add_argument("--log", required=True)
    p_count = sub.add_parser("count")
    p_count.add_argument("--log", required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "append":
            try:
                with open(args.record_file, "r", encoding="utf-8") as f:
                    record = json.load(f)
            except (OSError, ValueError) as e:
                print(f"file_log: error: cannot read record file: {e}",
                      file=sys.stderr)
                return 2
            saved = append_record(args.log, record)
            print(json.dumps({"status": "appended", "seq": saved["seq"],
                              "message_id": saved.get("message_id")},
                             ensure_ascii=False))
            return 0
        if args.command == "send-intent":
            saved = send_intent(args.log, args.project_id, args.message_id,
                                args.nonce, args.content_hash,
                                args.content_len)
            print(json.dumps({"status": "intent_recorded",
                              "seq": saved["seq"],
                              "message_id": saved["message_id"]},
                             ensure_ascii=False))
            return 0
        if args.command == "send-confirm":
            saved = send_confirm(args.log, args.message_id, args.outcome)
            print(json.dumps({"status": "outcome_recorded",
                              "seq": saved["seq"],
                              "message_id": saved["message_id"],
                              "outcome": args.outcome},
                             ensure_ascii=False))
            return 0
        if args.command == "mark-uncertain":
            saved = mark_uncertain(args.log, args.message_id, args.reason)
            print(json.dumps({"status": "marked_uncertain",
                              "seq": saved["seq"],
                              "message_id": saved["message_id"]},
                             ensure_ascii=False))
            return 0
        if args.command == "reconcile":
            verify_fn = None
            if args.verify_cmd:
                def verify_fn(mid, cmd=args.verify_cmd):
                    rendered = cmd.replace("{message_id}", mid)
                    out = subprocess.run(rendered, shell=True,
                                         capture_output=True, text=True,
                                         timeout=30)
                    verdict = (out.stdout or "").strip().split()[0] \
                        if (out.stdout or "").strip() else "unknown"
                    return verdict if verdict in (
                        "sent", "not_sent", "unknown") else "unknown"
            result = reconcile(args.log, verify_fn)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if not result["uncertain"] else 1
        if args.command == "uncertain":
            print(json.dumps({"uncertain": list_uncertain(args.log)},
                             ensure_ascii=False))
            return 0
        if args.command == "last":
            records = read_records(args.log)
            print(json.dumps(records[-1] if records else {},
                             ensure_ascii=False))
            return 0
        if args.command == "verify":
            result = verify_log(args.log)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["ok"] else 1
        if args.command == "count":
            print(json.dumps({"records": len(read_records(args.log))}))
            return 0
    except (ValueError, RuntimeError, OSError, TimeoutError) as e:
        print(f"file_log: error: {e}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
