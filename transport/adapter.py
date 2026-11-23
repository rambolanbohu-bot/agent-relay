#!/usr/bin/env python3
"""Agent Relay Skill v1.0.0-rc4-hotfix — 浏览器适配器调用接口（adapter.py）.

RC4-HOTFIX (FIX 4): send() now distinguishes MESSAGE_SENT from
RESPONSE_COMPLETED. A send_result with ok:true means the extension
confirmed the new user message is in the chat history
(delivery:"message_sent") — it NEVER means the AI reply is done
(that is RESPONSE_COMPLETED, reported separately by the completion
watch via reply_complete). A delivery of "uncertain" is never
treated as sent, even if ok were true; an unconfirmed send is
marked UNCERTAIN and never auto-resent.

RC4-HOTFIX5 (P2, ATTEMPT-08): B2 still failed on the real page —
the text stayed in the composer, the Adapter timed out, and the
send_result sat in the queue as send_unconfirmed. Two fixes here.
(1) _wait_outbox() read the outbox WITHOUT the FileLock while the
native host writes under it, and counted every line it looked at
as "seen" — a record read mid-write was lost forever, never
re-examined once complete. It now counts only COMPLETE lines
(terminated by "\\n") as seen, so a partial line is re-read on
the next poll. (2) Late receipts are reconciled, not dropped:
send() does one final _find_outbox_record() scan after a timeout,
and the new reconcile_send() upgrades an UNCERTAIN transaction
to delivered-late ONLY when the late receipt proves delivery
(ok:true + delivery message_sent + a non-null message_id from a
positively-identified new user node). A reply_started-only or
uncertain late receipt stays UNCERTAIN; a not_sent late receipt
marks it failed. NEVER auto-resend on UNCERTAIN. The safety
judgment is unchanged: read_latest() still truthfully returns
"not found" on found=false.

P0-1 的另一半：扩展本身是代码，协调器这边也要有一个**可调用的
接口**，而不是只有一份描述文档。本模块就是它：run.py 和 Muse 会话
通过它向扩展发命令（health / read_latest / send / poll / verify），
并拿到结构化的结果和验证记录。

两种模式：
- "native_host"（默认）：通过 transport/native_host.py 的文件队列
  （inbox.jsonl → 扩展 → outbox.jsonl）发命令。扩展在线时用它。
- "browser_task"（兜底）：native host / 扩展不在线时，send() 不硬发，
  而是返回一份结构化的 handoff（让 Muse 会话用浏览器任务去发），
  再由 record_browser_result() 把浏览器任务的结果补回发送事务。
  这样“扩展不在”不会静默失败，也不会绕过发送事务。

发送事务（见 orchestrator/file_log.py）：
  send_intent → 实际发送 → send_success / send_failed；
  发没发出去核实不了 → mark_uncertain 并停下，绝不自动重发。

来源绑定（Security-2b）：read_latest() 返回的每条回复都带 origin
（页面 origin，如 https://chatgpt.com）和 sender。sender 由 origin
决定（chatgpt.com → chatgpt；muse.ai → muse），不只看 sender 字段。
内容哈希由本模块重算比对；不一致 → 标记损坏，拒绝使用。

本模块绝不生成讨论内容：它只传输。下一轮的回复文本由 Muse 会话
现场生成，再经 send() 发出。

用法：
    from adapter import Adapter
    ad = Adapter(skill_root="/path/to/agent-relay-skill")
    print(ad.health("chatgpt"))
    print(ad.read_latest("chatgpt"))
    res = ad.send("chatgpt", text="你好", project_id="P-001")
    # res: {"ok": True, "message_id": ..., "nonce": ..., "mode": ...}
    # browser_task 模式下 res 是 {"ok": False, "handoff": {...}}，
    # 会话按 handoff 发完后调用 ad.record_browser_result(...)
"""

import hashlib
import json
import os
import secrets
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "orchestrator"))
import file_log  # noqa: E402
from locking import FileLock  # noqa: E402

SITE_ORIGINS = {
    "chatgpt": "https://chatgpt.com",
    "muse": "https://muse.ai",
}

# Errors that prove the message was definitely NOT sent.
DEFINITELY_NOT_SENT = {
    "composer_or_send_button_missing",
    "send_button_disabled_streaming",
    "composer_input_not_accepted",
    # HOTFIX 4 (P2-A): no send button ever appeared after the input,
    # and the content script never clicked, so the message was
    # definitely not sent.
    "send_button_missing_after_input",
    # HOTFIX 5 (P2, ATTEMPT-08): a button existed but never became
    # enabled after the input, so content.js never clicked (a click
    # on a disabled button is a DOM no-op). It joins the set
    # because the message definitely never left the composer;
    # treating it as UNCERTAIN would hide an honest not_sent
    # behind a timeout.
    "send_button_never_enabled",
    "empty_text",
    "no_tab_for_site:chatgpt.com",
    "no_tab_for_site:muse.ai",
    "content_script_unreachable",
}

DEFAULT_SEND_TIMEOUT = 60
DEFAULT_READ_TIMEOUT = 15


def _sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Adapter:
    def __init__(self, skill_root, mode="native_host"):
        self.skill_root = os.path.abspath(skill_root)
        self.state_dir = os.path.join(self.skill_root, "orchestrator",
                                      "state")
        self.log_path = os.path.join(self.state_dir, "discussion.jsonl")
        self.nh_dir = os.path.join(self.state_dir, "native_host")
        self.inbox = os.path.join(self.nh_dir, "inbox.jsonl")
        self.outbox = os.path.join(self.nh_dir, "outbox.jsonl")
        self.mode = mode

    # -- native host plumbing -------------------------------------------------

    def _nh_heartbeat_fresh(self, max_age_seconds=120):
        try:
            with open(os.path.join(self.nh_dir, "heartbeat.json"),
                      "r", encoding="utf-8") as f:
                beat = json.load(f)
            from datetime import datetime, timezone
            last = datetime.fromisoformat(beat.get("last_update", ""))
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - last).total_seconds()
            return 0 <= age <= max_age_seconds
        except (OSError, ValueError, KeyError):
            return False

    def native_host_connected(self):
        """True when the native host process looks alive (fresh heartbeat)."""
        return self._nh_heartbeat_fresh()

    def _read_secret(self):
        try:
            with open(os.path.join(self.nh_dir, "secret"), "r",
                      encoding="ascii") as f:
                return f.read().strip()
        except OSError:
            return None

    def _write_command(self, cmd):
        os.makedirs(self.nh_dir, exist_ok=True)
        secret = self._read_secret()
        cmd = dict(cmd)
        if secret:
            cmd["auth"] = secret
        with FileLock(self.inbox + ".lock", timeout=10):
            with open(self.inbox, "a", encoding="utf-8") as f:
                f.write(json.dumps(cmd, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())

    def _wait_outbox(self, nonce, timeout):
        """Wait for an outbox record whose envelope/host-error nonce matches.

        Returns the record, or None on timeout.

        HOTFIX 5 (P2, ATTEMPT-08): complete-line-only reading. The
        native host appends outbox lines under a FileLock, but this
        reader does NOT take the lock, so it can read a line mid-
        write. The old code counted every line it looked at as
        "seen" and skipped lines that failed to parse — so a record
        that was read while still partial was lost forever: it was
        never re-examined once complete. A send receipt can
        therefore arrive and be dropped, leaving the transaction
        UNCERTAIN even though the delivery evidence is sitting in
        the outbox (the ATTEMPT-08 "Adapter timeout" case). The
        outbox is append-only (never truncated), so this fix counts
        only COMPLETE lines — lines terminated by "\\n" — as seen,
        and never advances the cursor past a trailing partial line;
        the next poll re-reads that line once the writer finishes
        it. A line that is complete but unparseable is still
        skipped (it is genuinely corrupt, not mid-write).
        """
        deadline = time.time() + timeout
        seen = 0
        while time.time() < deadline:
            try:
                with open(self.outbox, "rb") as f:
                    raw = f.read()
            except FileNotFoundError:
                raw = b""
            # Only lines terminated by "\n" are complete records.
            # The bytes after the last "\n" (if any) are a partial
            # line still being written; they are NOT counted as seen.
            complete = raw.split(b"\n")
            complete.pop()
            for i in range(seen, len(complete)):
                seen = i + 1
                try:
                    rec = json.loads(complete[i].decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                env = rec.get("envelope") or {}
                if env.get("nonce") == nonce or rec.get("nonce") == nonce:
                    return rec
            time.sleep(0.2)
        return None

    def _find_outbox_record(self, nonce):
        """Full scan of the outbox for a record matching this nonce.

        HOTFIX 5 (P2, ATTEMPT-08): used for the late-receipt
        reconciliation (see send() / reconcile_send()). Scans the
        whole outbox — only complete lines (terminated by "\\n");
        a trailing partial line is ignored, exactly as in
        _wait_outbox — and returns the LAST matching complete
        record, or None. Unlike _wait_outbox it does not stop at a
        deadline; it is a one-shot lookup, so it is safe to call
        after a timeout.
        """
        try:
            with open(self.outbox, "rb") as f:
                raw = f.read()
        except FileNotFoundError:
            return None
        complete = raw.split(b"\n")
        # The last element is a partial line unless the file ends
        # with "\n" (in which case it is empty). Drop it either way.
        complete.pop()
        found = None
        for line in complete:
            try:
                rec = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            env = rec.get("envelope") or {}
            if env.get("nonce") == nonce or rec.get("nonce") == nonce:
                found = rec
        return found

    def _record_op(self, project_id, op, nonce, status, detail=None,
                   content=None, origin=None):
        record = {
            "kind": "adapter_op",
            "project_id": project_id or "",
            "op": op,
            "nonce": nonce,
            "status": status,
            "mode": self.mode,
        }
        if detail:
            record["detail"] = detail
        if origin:
            record["origin"] = origin
        if content is not None:
            record["content"] = content
        try:
            file_log.append_record(self.log_path, record)
        except Exception:
            pass  # state logging must never break the operation itself

    # -- operations -----------------------------------------------------------

    def health(self, site, project_id=""):
        nonce = secrets.token_hex(8)
        if self.mode == "browser_task" or not self.native_host_connected():
            return {"ok": False, "mode": self.mode,
                    "error": "native_host_not_connected",
                    "nonce": nonce,
                    "handoff": {"action": "health_check",
                                "site": site,
                                "check": "composer_and_send_button_present"}}
        self._write_command({"id": "cmd-" + nonce, "type": "health",
                             "site": site, "nonce": nonce})
        rec = self._wait_outbox(nonce, DEFAULT_READ_TIMEOUT)
        if rec is None:
            self._record_op(project_id, "health", nonce, "timeout")
            return {"ok": False, "error": "timeout", "nonce": nonce}
        env = rec.get("envelope") or {}
        ok = bool(env.get("ok"))
        self._record_op(project_id, "health", nonce,
                        "ok" if ok else "failed",
                        detail=env.get("error"),
                        origin=env.get("origin"))
        return {"ok": ok, "nonce": nonce, "detail": env}

    def read_latest(self, site, project_id=""):
        """Read the latest assistant reply from the site's tab.

        Returns {"ok", "found", "sender", "origin", "content",
        "content_sha256", "streaming", ...}. The content hash is recomputed
        here; a mismatch is reported as corrupt and the content is NOT
        returned as usable.
        """
        nonce = secrets.token_hex(8)
        if self.mode == "browser_task" or not self.native_host_connected():
            return {"ok": False, "mode": self.mode,
                    "error": "native_host_not_connected",
                    "nonce": nonce,
                    "handoff": {"action": "read_latest", "site": site,
                                "instruction": "read the latest assistant "
                                "reply in full from the tab; do not scroll "
                                "or activate it"}}
        self._write_command({"id": "cmd-" + nonce, "type": "read_latest",
                             "site": site, "nonce": nonce})
        rec = self._wait_outbox(nonce, DEFAULT_READ_TIMEOUT)
        if rec is None:
            self._record_op(project_id, "read_latest", nonce, "timeout")
            return {"ok": False, "error": "timeout", "nonce": nonce}
        env = rec.get("envelope") or {}
        if not env.get("found"):
            self._record_op(project_id, "read_latest", nonce, "not_found")
            # HOTFIX 6: attach the de-sensitized diagnostic
            # inventory so ATTEMPT-10 can capture the real structure.
            return {"ok": True, "found": False, "nonce": nonce,
                    "diagnostics": env.get("diagnostics")}
        content = env.get("content") or ""
        claimed = env.get("content_sha256")
        actual = _sha256(content)
        if claimed and claimed != actual:
            self._record_op(project_id, "read_latest", nonce, "corrupt",
                            origin=env.get("origin"))
            return {"ok": False, "error": "hash_mismatch", "nonce": nonce}
        # Provenance is bound to the page origin, not just the sender field.
        origin = env.get("origin") or SITE_ORIGINS.get(site, "")
        sender = "chatgpt" if "chatgpt.com" in origin else \
            "muse" if "muse.ai" in origin else env.get("sender", "unknown")
        self._record_op(project_id, "read_latest", nonce, "ok",
                        content=content, origin=origin)
        return {"ok": True, "found": True, "sender": sender,
                "origin": origin, "content": content,
                "content_sha256": actual,
                "content_len": len(content),
                "streaming": bool(env.get("streaming")),
                "strategy": env.get("strategy"),
                "nonce": nonce}

    def collect_dom(self, site, user_marker, assistant_marker,
                    project_id=""):
        """Collect the de-sensitized DOM structure for two known test
        markers (HOTFIX 6, ROUND 25).

        Optional read-only diagnostic mode: the content script
        matches the two marker texts in the page and returns ONLY
        de-sensitized structure - whether each marker was found, how
        many nodes the role selectors match, and the tag / role /
        testid / class / parent chain of the two matched nodes (up
        to 12 levels). NO message content, NO cookie, NO token, NO
        URL, NO real message id, NO network upload, and it does not
        read the whole history. Key diagnostic: user_found=True
        with role_selector_counts.user=0 is direct evidence the
        user role selector is broken; same for assistant.

        Returns {"ok", "nonce", "detail"} where detail is the full
        de-sensitized JSON, or an error return on timeout / no host.
        """
        nonce = secrets.token_hex(8)
        if self.mode == "browser_task" or not self.native_host_connected():
            return {"ok": False, "mode": self.mode,
                    "error": "native_host_not_connected",
                    "nonce": nonce,
                    "handoff": {"action": "collect_dom", "site": site,
                                "instruction": "run the read-only "
                                "de-sensitized DOM collector in the tab "
                                "for the two test markers; return the "
                                "JSON, do not scroll or activate it"}}
        self._write_command({"id": "cmd-" + nonce, "type": "collect_dom",
                             "site": site, "nonce": nonce,
                             "user_marker": user_marker,
                             "assistant_marker": assistant_marker})
        rec = self._wait_outbox(nonce, DEFAULT_READ_TIMEOUT)
        if rec is None:
            self._record_op(project_id, "collect_dom", nonce, "timeout")
            return {"ok": False, "error": "timeout", "nonce": nonce}
        env = rec.get("envelope") or {}
        if not env.get("ok"):
            self._record_op(project_id, "collect_dom", nonce, "failed",
                            detail=env.get("error"),
                            origin=env.get("origin"))
            return {"ok": False, "error": env.get("error") or "failed",
                    "nonce": nonce, "detail": env}
        counts = env.get("role_selector_counts") or {}
        summary = ("user_found=%s assistant_found=%s "
                   "role_user=%s role_assistant=%s"
                   % (env.get("user_found"), env.get("assistant_found"),
                      counts.get("user"), counts.get("assistant")))
        self._record_op(project_id, "collect_dom", nonce, "ok",
                        detail=summary, origin=env.get("origin"))
        return {"ok": True, "nonce": nonce, "detail": env}

    def send(self, site, text, project_id="", nonce=None,
             timeout=DEFAULT_SEND_TIMEOUT):
        """Send one message via the send transaction.

        Returns {"ok": True, "message_id", "nonce",
        "delivery": "message_sent"} on confirmed send. ok:true means
        MESSAGE_SENT only — the extension confirmed the new user
        message is in the chat history. It NEVER means the AI reply is
        done (RESPONSE_COMPLETED, reported separately by the
        completion watch). {"ok": False, "error": ...,
        "uncertain": bool, "delivery": ...} otherwise.
        In browser_task mode (or when the native host is down) it records
        the intent and returns a handoff instead of sending.
        """
        if not text or not text.strip():
            return {"ok": False, "error": "empty_text"}
        # Fail closed before creating a send intent if Muse's content script
        # cannot answer a read-only probe (e.g., after extension reload).
        # This is only a pre-dispatch gate; post-dispatch uncertainty remains
        # UNCERTAIN and must never be automatically retried.
        if site == "muse" and self.mode != "browser_task":
            if not self.native_host_connected():
                return {"ok": False, "error": "muse_native_host_preflight_failed",
                        "delivery": "not_sent"}
            probe = self.health(site, project_id)
            detail = probe.get("detail") or {}
            if not (probe.get("ok") is True and detail.get("ok") is True
                    and detail.get("composer_found") is True
                    and detail.get("document_readiness_verified") is True):
                return {"ok": False, "error": "muse_content_script_preflight_failed",
                        "delivery": "not_sent", "preflight_error": detail.get("error")
                        or probe.get("error") or "composer_or_document_not_ready"}
        nonce = nonce or secrets.token_hex(8)
        message_id = "m-" + nonce
        content_hash = _sha256(text)
        file_log.send_intent(self.log_path, project_id, message_id, nonce,
                             content_hash, len(text))
        if self.mode == "browser_task" or not self.native_host_connected():
            self._record_op(project_id, "send", nonce, "handoff",
                            detail="native_host_not_connected")
            return {"ok": False, "error": "native_host_not_connected",
                    "handoff": {"action": "send_via_browser_task",
                                "site": site, "text": text,
                                "message_id": message_id, "nonce": nonce,
                                "instruction": "fill the composer with the "
                                "text via DOM and click send; do not "
                                "activate the tab"},
                    "message_id": message_id, "nonce": nonce}
        self._write_command({"id": "cmd-" + nonce, "type": "send",
                             "site": site, "text": text, "nonce": nonce})
        rec = self._wait_outbox(nonce, timeout)
        if rec is None:
            # HOTFIX 5 (P2, ATTEMPT-08): before declaring a timeout,
            # do ONE final full scan of the outbox. A receipt that
            # arrived after the deadline — or that _wait_outbox
            # missed because it was read mid-write — must be
            # reconciled, not dropped. If a receipt is found it is
            # processed exactly like an on-time one, but marked
            # "late": True with its arrival time, so the caller can
            # tell a late delivery from an on-time one. If no
            # receipt exists, the transaction is UNCERTAIN, never
            # auto-resent — exactly as before.
            rec = self._find_outbox_record(nonce)
            if rec is not None:
                return self._process_send_receipt(
                    rec, message_id, project_id, nonce, late=True)
            # Sent or not? We cannot verify — UNCERTAIN, never auto-resend.
            file_log.mark_uncertain(
                self.log_path, message_id,
                reason="no send confirmation within timeout")
            self._record_op(project_id, "send", nonce, "uncertain")
            return {"ok": False, "error": "timeout", "uncertain": True,
                    "delivery": "uncertain",
                    "message_id": message_id, "nonce": nonce}
        return self._process_send_receipt(rec, message_id, project_id,
                                          nonce)

    def _process_send_receipt(self, rec, message_id, project_id, nonce,
                              late=False):
        """Turn one outbox send_result receipt into send()'s return
        value and the matching state-log entry.

        Shared by the on-time path (send() after _wait_outbox) and
        the late path (send() after a timeout + _find_outbox_record,
        and reconcile_send()). "late" only changes the audit
        record: the result carries "late": True and the receipt's
        arrival time, so a late delivery is reported as
        delivered-late, never silently rewritten as on-time.
        The safety rules are identical for both paths: a delivery
        of "uncertain" is never treated as sent; a DEFINITELY_NOT_
        SENT error is a failure; anything ambiguous is UNCERTAIN.
        """
        from datetime import datetime, timezone
        env = rec.get("envelope") or {}
        if rec.get("direction") == "host_error" or not env.get("ok", True):
            err = env.get("error") or rec.get("error") or "send_failed"
            if err in DEFINITELY_NOT_SENT or err.startswith("no_tab_for_site"):
                file_log.send_confirm(self.log_path, message_id, "failed")
                self._record_op(project_id, "send", nonce,
                                "failed_late" if late else "failed",
                                detail=err)
                # HOTFIX 6 (B4): attach the button time series and
                # the tab visibility state so a not_sent failure on
                # a hidden tab can be told from a visible-tab one.
                out = {"ok": False, "error": err,
                       "delivery": "not_sent",
                       "message_id": message_id, "nonce": nonce,
                       "button_timeline": env.get("button_timeline"),
                       "visibility_state": env.get("visibility_state")}
                if late:
                    out["late"] = True
                return out
            file_log.mark_uncertain(
                self.log_path, message_id,
                reason=f"ambiguous send error: {err}")
            self._record_op(project_id, "send", nonce,
                            "uncertain_late" if late else "uncertain",
                            detail=err)
            out = {"ok": False, "error": err, "uncertain": True,
                   "delivery": "uncertain",
                   "message_id": message_id, "nonce": nonce,
                   "diagnostics": env.get("diagnostics"),
                   "button_timeline": env.get("button_timeline"),
                   "visibility_state": env.get("visibility_state")}
            if late:
                out["late"] = True
            return out
        # FIX 4 (RC4-hotfix): a delivery of "uncertain" is never
        # treated as sent, even if ok were true. ok:true means
        # MESSAGE_SENT only, never RESPONSE_COMPLETED.
        if env.get("delivery") == "uncertain":
            file_log.mark_uncertain(
                self.log_path, message_id,
                reason="extension reported delivery uncertain")
            self._record_op(project_id, "send", nonce,
                            "uncertain_late" if late else "uncertain",
                            detail=env.get("error"))
            # HOTFIX 6: attach the de-sensitized diagnostic
            # inventory and the button time series.
            out = {"ok": False,
                   "error": env.get("error") or "send_unconfirmed",
                   "uncertain": True, "delivery": "uncertain",
                   "message_id": message_id, "nonce": nonce,
                   "diagnostics": env.get("diagnostics"),
                   "button_timeline": env.get("button_timeline"),
                   "visibility_state": env.get("visibility_state")}
            if late:
                out["late"] = True
            return out
        # HOTFIX 5 (P2): a LATE receipt upgrades the transaction
        # ONLY when it proves delivery of THIS message: ok:true +
        # delivery "message_sent" + a non-null message_id. The
        # message_id is bound by content.js only to a
        # positively-identified new user node; a reply_started-only
        # receipt carries message_id null (the AI replying proves
        # SOME message was delivered, not necessarily this one), so
        # it does NOT upgrade — it stays UNCERTAIN with the
        # evidence attached. The on-time path keeps its existing
        # rule (a reply_started confirmation is accepted as
        # delivered while the send is still in flight); the bar is
        # higher once the transaction has already timed out.
        if late and not env.get("message_id"):
            file_log.mark_uncertain(
                self.log_path, message_id,
                reason="late receipt has no message_id: "
                       "reply_started only, delivery not proven")
            self._record_op(project_id, "send", nonce, "uncertain_late",
                            detail=env.get("confirmation"))
            return {"ok": False,
                    "error": env.get("error") or "send_unconfirmed",
                    "uncertain": True, "delivery": "uncertain",
                    "message_id": message_id, "nonce": nonce,
                    "late": True,
                    "late_evidence": env}
        file_log.send_confirm(self.log_path, message_id, "sent")
        self._record_op(project_id, "send", nonce,
                        "ok_late" if late else "ok",
                        origin=env.get("origin"))
        out = {"ok": True, "message_id": message_id, "nonce": nonce,
               "delivery": env.get("delivery", "message_sent"),
               "detail": env}
        if late:
            out["late"] = True
            out["late_arrival_time"] = datetime.now(timezone.utc).isoformat()
        return out

    def reconcile_send(self, message_id):
        """Reconcile a send transaction that was left UNCERTAIN.

        HOTFIX 5 (P2, ATTEMPT-08): a send_result receipt can arrive
        AFTER send() timed out (slow page, throttled tab, or the
        pre-Hotfix5 _wait_outbox mid-write race). Before Hotfix5
        that receipt sat in the outbox forever and the transaction
        stayed UNCERTAIN. reconcile_send() checks the state log
        first, then the outbox, and upgrades the transaction ONLY
        when the late receipt PROVES delivery: it must carry a
        matching message_id AND nonce, be ok:true, have delivery
        "message_sent" (not "uncertain"), and carry a non-null
        message_id from a positively-identified new user node
        (content.js binds message_id only to such a node). A
        reply_started-only receipt (no message_id) or an uncertain
        receipt does NOT upgrade — it stays UNCERTAIN with the
        evidence attached. A not_sent receipt marks the
        transaction failed. It NEVER auto-resends: reconciliation
        only re-reads evidence that already exists.
        Returns {"status": "sent"|"not_sent"|"uncertain"|"unknown",
        "message_id": ..., "late": bool, "evidence": ...}.

        The upgrade is recorded durably with file_log.
        send_reconciled() — NOT send_confirm(): the transaction was
        already marked UNCERTAIN, and file_log's one-outcome rule
        forbids a second send_success / send_failed / send_uncertain
        for the same message_id. send_reconciled() is the dedicated
        kind for this upgrade (allowed only after a send_uncertain,
        only once); the original send_uncertain record stands as
        history and this record is the audit trail. A second call
        returns the already-recorded reconciliation (idempotent).
        """
        records = file_log.read_records(self.log_path)
        for rec in records:
            if rec.get("message_id") != message_id:
                continue
            if rec.get("kind") == "send_success":
                return {"status": "sent", "message_id": message_id,
                        "late": False, "evidence": "state_log"}
            if rec.get("kind") == "send_failed":
                return {"status": "not_sent", "message_id": message_id,
                        "late": False, "evidence": "state_log"}
            if rec.get("kind") == "send_reconciled":
                return {"status": rec.get("status"), "message_id": message_id,
                        "late": True,
                        "evidence": rec.get("evidence") or "state_log"}
        # No terminal state in the log: look for a late receipt.
        # The nonce is the transaction id after "m-".
        nonce = message_id[2:] if message_id.startswith("m-") else None
        if not nonce:
            return {"status": "unknown", "message_id": message_id,
                    "late": False,
                    "evidence": "message_id has no nonce"}
        rec = self._find_outbox_record(nonce)
        if rec is None:
            return {"status": "uncertain", "message_id": message_id,
                    "late": False,
                    "evidence": "no late receipt in outbox"}
        env = rec.get("envelope") or {}
        # Only a receipt that PROVES delivery upgrades the
        # transaction: ok:true + delivery message_sent + a
        # positively-identified new user node (message_id present).
        # A reply_started-only receipt (no message_id) proves the
        # AI replied, not that THIS message was delivered — it
        # stays UNCERTAIN with the evidence attached.
        if env.get("ok") and env.get("delivery") == "message_sent" \
                and env.get("message_id"):
            file_log.send_reconciled(
                self.log_path, message_id, "sent",
                reason="late receipt proves delivery",
                evidence={"message_id": env.get("message_id"),
                          "confirmation": env.get("confirmation"),
                          "origin": env.get("origin")})
            self._record_op("", "send", nonce, "ok_late",
                            origin=env.get("origin"))
            return {"status": "sent", "message_id": message_id,
                    "late": True, "evidence": env}
        if rec.get("direction") == "host_error" or not env.get("ok", True):
            err = env.get("error") or rec.get("error") or "send_failed"
            if err in DEFINITELY_NOT_SENT \
                    or err.startswith("no_tab_for_site"):
                file_log.send_reconciled(
                    self.log_path, message_id, "failed",
                    reason=f"late receipt proves not sent: {err}",
                    evidence={"error": err})
                self._record_op("", "send", nonce, "failed_late",
                                detail=err)
                return {"status": "not_sent", "message_id": message_id,
                        "late": True, "evidence": env}
        return {"status": "uncertain", "message_id": message_id,
                "late": True, "evidence": env}

    def record_browser_result(self, message_id, outcome, reason=""):
        """Complete a send transaction after a browser-task send.

        outcome: "sent" (confirmed delivered) or "failed" (definitely not
        sent). If the outcome cannot be confirmed, call with "unknown"
        instead — it marks the send UNCERTAIN.
        """
        if outcome == "sent":
            file_log.send_confirm(self.log_path, message_id, "sent")
            return {"ok": True, "outcome": "sent"}
        if outcome == "failed":
            file_log.send_confirm(self.log_path, message_id, "failed")
            return {"ok": True, "outcome": "failed"}
        file_log.mark_uncertain(self.log_path, message_id,
                                reason=reason or "browser result unknown")
        return {"ok": False, "outcome": "uncertain"}

    def verify(self, message_id):
        """Verify a pending send for reconcile(): "sent" / "not_sent" /
        "unknown". Checks the state log first, then the native-host outbox
        for a matching send_result.
        """
        records = file_log.read_records(self.log_path)
        for rec in records:
            if rec.get("message_id") != message_id:
                continue
            if rec.get("kind") == "send_success":
                return "sent"
            if rec.get("kind") == "send_failed":
                return "not_sent"
        try:
            with open(self.outbox, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    env = rec.get("envelope") or {}
                    if env.get("type") == "send_result" and \
                            env.get("nonce") and \
                            ("m-" + env["nonce"]) == message_id:
                        return "sent" if env.get("ok") else "not_sent"
        except FileNotFoundError:
            pass
        return "unknown"


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Agent Relay adapter CLI")
    parser.add_argument("--skill-root", required=True)
    parser.add_argument("--mode", default="native_host",
                        choices=["native_host", "browser_task"])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("health", "read_latest"):
        p = sub.add_parser(name)
        p.add_argument("--site", default="chatgpt")
        p.add_argument("--project-id", default="")
    p_send = sub.add_parser("send")
    p_send.add_argument("--site", default="chatgpt")
    p_send.add_argument("--project-id", default="")
    p_send.add_argument("--text-file", required=True)
    p_verify = sub.add_parser("verify")
    p_verify.add_argument("--message-id", required=True)
    args = parser.parse_args(argv)
    ad = Adapter(args.skill_root, mode=args.mode)
    # Escape non-ASCII in CLI JSON so legacy Windows stdout can print receipts.
    if args.command == "health":
        print(json.dumps(ad.health(args.site, args.project_id)))
        return 0
    if args.command == "read_latest":
        print(json.dumps(ad.read_latest(args.site, args.project_id)))
        return 0
    if args.command == "send":
        with open(args.text_file, "r", encoding="utf-8") as f:
            text = f.read()
        res = ad.send(args.site, text, args.project_id)
        print(json.dumps(res))
        return 0 if res.get("ok") else 1
    if args.command == "verify":
        print(json.dumps({"message_id": args.message_id,
                          "verdict": ad.verify(args.message_id)}))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
