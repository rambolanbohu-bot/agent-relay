#!/usr/bin/env python3
"""Agent Relay Skill v1.0.0-rc4-hotfix — 协调器可执行入口（run.py）.

RC4-HOTFIX (FIX 2, P0): the project state machine now reads the
latest state. _project() used to return the latest kind=="project"
record (the creation record, status CREATED) and never read the
kind=="project_status" records _set_status() writes — so pause /
complete never showed in status and advance()'s COMPLETED/BLOCKED
guard never triggered. _project() now merges the latest
project_status record (latest-wins by log sequence) over the
creation record. State restrictions are enforced: CREATED and
DISCUSSING allow advance; PAUSED refuses advance (resume first);
COMPLETED and BLOCKED refuse advance; resume/pause/complete also
refuse on terminal states. A fresh Runner on the same log (restart
recovery) sees the same terminal states, because the log is the
only source of truth and reads are append-only, latest-wins.

P0-2 修复：RC1 只有 orchestrator.md（步骤说明），没有可运行的入口。
本文件是 v1 的自动协作执行入口：建项目、推轮次、断点续跑、查状态。
它驱动 transport/adapter.py、orchestrator/file_log.py、
orchestrator/watchdog.py 和 approvals/approvals.py。

诚实边界（条件 5）——本文件能做什么、不能做什么：
(a) Python 协调器能自动做的：建项目、记状态、去重、算哈希、看门狗
    检查、经适配器收发消息、发送事务与对账、审批检查门。
(b) Muse 会话做的模型任务：生成每一轮的回复文本、判断是否收敛、
    写决策包、向用户汇报。回复文本一律由模型现场生成，run.py
    绝不编造、绝不用预写文本。
(c) 需要用户干预的：批准决策、重新登录、处理页面改版、处理
    UNCERTAIN 发送。
Muse handoff 自动唤醒（程序触发 Muse 会话自动生成下一轮）：
    **NOT YET IMPLEMENTED**——run.py 推进状态不等于能自动唤醒 Muse。
    每轮的模型步骤仍需一次 Muse 会话执行（定时任务唤醒或用户在场）。
    GATE-AUTONOMY 绝不能只凭 stub 测试就标 PASS。
    这一点在 status 输出里每次都写明。

用法：
    python3 run.py --skill-root /path/to/agent-relay-skill \
        create --topic "比较三种装修方案" [--mode discussion]
    python3 run.py --skill-root ... advance --project-id P-XXXX \
        [--reply-file /path/to/reply.txt] [--site chatgpt]
    python3 run.py --skill-root ... resume --project-id P-XXXX
    python3 run.py --skill-root ... status [--project-id P-XXXX]
    python3 run.py --skill-root ... reconcile --project-id P-XXXX
    python3 run.py --skill-root ... pause --project-id P-XXXX \
        --reason "..."
    python3 run.py --skill-root ... complete --project-id P-XXXX \
        --reason "consensus reached"
    python3 run.py --skill-root ... set-mode --project-id P-XXXX \
        --mode execution
    python3 run.py --skill-root ... execute --project-id P-XXXX \
        --decision-id DEC-... --operation-id OP-1 \
        --params-file /path/to/params.json

两种模式（RC3 引入，RC4 保持）：
- Discussion（默认）：只交换文本、分析、生成提案；不做任何对外
  生效的操作；不需要批准。create / advance / resume / reconcile /
  pause / complete / status 都属于这一模式。
- Execution：执行对外生效的操作（目前白名单只有一个动作：
  write_file——把一份摘要文件写进本项目目录）。执行前必须同时
  满足两点：项目已切换到 execution 模式，并且有一份来自本地审批页
  的批准（approvals.py 的检查门，绑定决策、操作、参数摘要与审批
  人，并在执行时重新核对整条批准记录）。Muse 审批卡在 RC4 里已
  禁用，不能授权执行（platform_receipt_disabled）。缺任何一点都
  拒绝（默认拒绝）。切换模式用 set-mode。

advance 的工作方式（每轮）：
  1. 先对账：有未确认的发送 → 用适配器核实；核实不了 → UNCERTAIN，
     停下（不自动重发）。
  2. 读最新回复：有新回复 → 记盘，输出 NEXT_ROUND 块（回复全文 +
     请模型生成下一轮的提示），退出码 0；模型生成好回复文本后，
     再调一次 advance --reply-file <文件> 把回复发出去。
  3. 带 --reply-file 时：按发送事务发出去，轮次 +1；到 3 轮上限 →
     状态 REVIEWING，等模型判断收敛或生成决策包。
  4. 无新回复、无 reply-file → 输出 waiting_for_reply，退出码 0。
"""

import argparse
import hashlib
import json
import os
import secrets
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "transport"))
sys.path.insert(0, os.path.join(HERE, "..", "approvals"))

import file_log  # noqa: E402
import watchdog  # noqa: E402
from adapter import Adapter  # noqa: E402
from approvals import ApprovalStore, _canonical, _sha256 as _appr_sha256  # noqa: E402

MAX_ROUNDS = 3
MAX_CONTENT_CHARS = 8000
MODES = ("discussion", "execution")
# 执行白名单（RC3）：目前只有一个对外生效的动作。加新动作必须同时
# 更新 approvals 的决策包与这里的白名单检查，不能悄悄放行。
EXECUTION_WHITELIST = ("write_file",)

HONESTY_BLOCK = {
    "two_modes": (
        "Discussion (default): exchange text, analyse, generate "
        "proposals; NO externally-effective operations; no approval "
        "needed. Execution: externally-effective operations (whitelist "
        "only, currently write_file); requires the project to be in "
        "execution mode AND a local-approval-page approval bound to the "
        "decision, operation, params digest and approver, re-verified "
        "at execution time. Default-deny: missing either one refuses "
        "the operation."
    ),
    "approval_channel_rc4": (
        "Execution accepts ONLY local-approval-page credentials "
        "(install PIN + single-use session token + decision-bound "
        "nonce). The Muse approval card is a notification/display "
        "channel only in RC4 — it cannot authorize execution "
        "(platform_receipt_disabled) until the platform can provide a "
        "verifiable approval result. GATE-HITL stays PENDING."
    ),
    "python_coordinator_can_do_automatically": [
        "create projects, record state, dedup, hash content",
        "watchdog staleness checks",
        "send/receive via the browser adapter (extension + native host)",
        "send transactions and restart reconciliation (UNCERTAIN -> pause)",
        "approval pre-execution gate enforcement",
    ],
    "muse_session_model_tasks": [
        "generate each round's reply text (live, in-session)",
        "judge convergence (open objections = 0 and two consecutive accepts)",
        "write the decision package for the user",
        "report results to the user",
    ],
    "needs_user_intervention": [
        "approve / reject decisions",
        "re-login to ChatGPT when the session expires",
        "handle page redesigns and UNCERTAIN sends",
    ],
    "muse_handoff_auto_wake": (
        "NOT YET IMPLEMENTED: run.py advancing state does NOT prove it can "
        "auto-wake a Muse session and generate the next round. Each round's "
        "model step still needs a Muse session run (scheduled wake or a "
        "user-present session). GATE-AUTONOMY must NOT be marked PASS from "
        "stub tests."
    ),
}


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Runner:
    def __init__(self, skill_root, mode="native_host"):
        self.skill_root = os.path.abspath(skill_root)
        self.state_dir = os.path.join(self.skill_root, "orchestrator",
                                      "state")
        self.log_path = os.path.join(self.state_dir, "discussion.jsonl")
        self.heartbeat_path = os.path.join(self.state_dir,
                                           "heartbeat.json")
        self.approvals_path = os.path.join(self.state_dir,
                                           "approvals.json")
        self.approval_store = ApprovalStore(self.approvals_path)
        self.adapter = Adapter(self.skill_root, mode=mode)

    def _mode(self, project_id):
        """Current mode of a project: 'discussion' (default) or
        'execution'. The latest project_mode record wins."""
        mode = "discussion"
        for rec in self._records():
            if rec.get("project_id") != project_id:
                continue
            if rec.get("kind") == "project_mode":
                mode = rec.get("mode", mode)
            elif rec.get("kind") == "project" and rec.get("mode"):
                mode = rec.get("mode")
        return mode if mode in MODES else "discussion"

    # -- state helpers ------------------------------------------------------

    def _records(self):
        return file_log.read_records(self.log_path)

    def _project_records(self, project_id):
        return [r for r in self._records()
                if r.get("project_id") == project_id]

    def _project(self, project_id):
        """Latest project state: the creation record merged with the
        latest project_status record (latest-wins by log sequence).

        FIX 2 (P0, RC4-hotfix): the old version returned the latest
        kind=="project" record — the creation record, always status
        CREATED — and never read the kind=="project_status" records
        _set_status() writes, so pause/complete never showed and
        advance()'s COMPLETED/BLOCKED guard never triggered. The log
        is append-only; old events never overwrite new ones. Returns
        a copy; never mutates the log records."""
        base = None
        status = None
        detail = None
        for rec in self._records():
            if rec.get("project_id") != project_id:
                continue
            if rec.get("kind") == "project" and base is None:
                base = dict(rec)
            elif rec.get("kind") == "project_status":
                status = rec.get("status")
                detail = rec.get("detail", "")
        if base is None:
            return None
        if status is not None:
            base["status"] = status
            base["status_detail"] = detail
        return base

    def _is_terminal(self, project):
        return project is not None and project.get("status") in (
            "COMPLETED", "BLOCKED")

    def _last_message(self, project_id, sender=None):
        for rec in reversed(self._records()):
            if rec.get("kind") != "message":
                continue
            if rec.get("project_id") != project_id:
                continue
            if sender and rec.get("sender") != sender:
                continue
            return rec
        return None

    def _turn_number(self, project_id):
        n = 0
        for rec in self._records():
            if rec.get("project_id") == project_id \
                    and rec.get("kind") == "message":
                n = max(n, rec.get("turn_number", 0))
        return n

    def _write_heartbeat(self, project_id, status):
        beat = {"project_id": project_id, "last_update": _utcnow(),
                "turn_number": self._turn_number(project_id),
                "status": status}
        tmp = self.heartbeat_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(beat, f, ensure_ascii=False)
        os.replace(tmp, self.heartbeat_path)
        return beat

    def _set_status(self, project_id, status, detail=""):
        file_log.append_record(self.log_path, {
            "kind": "project_status",
            "project_id": project_id,
            "status": status,
            "detail": detail,
        })

    # -- commands -------------------------------------------------------------

    def create(self, topic, project_id=None, mode="discussion"):
        project_id = project_id or ("P-" + secrets.token_hex(4).upper())
        if mode not in MODES:
            print(json.dumps({"error": "bad_mode", "mode": mode},
                             ensure_ascii=False))
            return 2
        if self._project(project_id) is not None:
            print(json.dumps({"error": "project_exists",
                              "project_id": project_id}, ensure_ascii=False))
            return 1
        file_log.append_record(self.log_path, {
            "kind": "project",
            "project_id": project_id,
            "topic": topic,
            "status": "CREATED",
            "mode": mode,
            "max_rounds": MAX_ROUNDS,
        })
        self._write_heartbeat(project_id, "CREATED")
        print(json.dumps({
            "status": "created",
            "project_id": project_id,
            "topic": topic,
            "next": "generate round 1 in the Muse session, then run: "
                    "advance --project-id %s --reply-file <reply.txt>"
                    % project_id,
            "honesty": HONESTY_BLOCK["muse_handoff_auto_wake"],
        }, ensure_ascii=False))
        return 0

    def _reconcile_or_pause(self, project_id):
        """Reconcile pending sends. Returns (ok, uncertain_list)."""
        result = file_log.reconcile(
            self.log_path,
            verify_fn=lambda mid: self.adapter.verify(mid))
        if result["uncertain"]:
            self._set_status(
                project_id, "PAUSED_UNCERTAIN",
                detail="uncertain sends: %s" % ",".join(result["uncertain"]))
            return False, result["uncertain"]
        return True, []

    def advance(self, project_id, reply_file=None, site="chatgpt"):
        project = self._project(project_id)
        if project is None:
            print(json.dumps({"error": "project_not_found",
                              "project_id": project_id}, ensure_ascii=False))
            return 1
        # FIX 2 (P0): enforce state restrictions on the MERGED status.
        # CREATED and DISCUSSING allow advance; PAUSED refuses (resume
        # first); COMPLETED and BLOCKED refuse.
        status = project.get("status")
        if status in ("COMPLETED", "BLOCKED"):
            print(json.dumps({"error": "project_closed",
                              "status": status,
                              "project_id": project_id},
                             ensure_ascii=False))
            return 1
        if status == "PAUSED":
            print(json.dumps({
                "error": "project_paused",
                "status": "PAUSED",
                "project_id": project_id,
                "instruction": "This project is paused. Resume it "
                               "first: resume --project-id %s" % project_id,
            }, ensure_ascii=False))
            return 1
        # 1. Reconcile first: never advance on top of an unverified send.
        ok, uncertain = self._reconcile_or_pause(project_id)
        if not ok:
            print(json.dumps({
                "status": "paused_uncertain",
                "project_id": project_id,
                "uncertain": uncertain,
                "instruction": "A send may have gone through but cannot be "
                               "verified. Do NOT auto-resend. Ask the user "
                               "to confirm whether the message arrived, then "
                               "resume with: resume --project-id %s"
                               % project_id,
            }, ensure_ascii=False))
            return 1
        # Reconcile passed: the project is active again. Record the
        # transition out of CREATED (first advance) or out of a stale
        # PAUSED_UNCERTAIN (its sends have now been verified), so the
        # log state matches reality.
        if status in ("CREATED", "PAUSED_UNCERTAIN"):
            self._set_status(project_id, "DISCUSSING", detail="advance")
        # 2. If the model has generated a reply, send it.
        if reply_file:
            try:
                with open(reply_file, "r", encoding="utf-8") as f:
                    text = f.read()
            except OSError as e:
                print(json.dumps({"error": f"cannot read reply file: {e}"},
                                 ensure_ascii=False))
                return 2
            if not text.strip():
                print(json.dumps({"error": "reply file is empty"},
                                 ensure_ascii=False))
                return 2
            if len(text) > MAX_CONTENT_CHARS:
                print(json.dumps(
                    {"error": f"reply too long: {len(text)} chars, max "
                              f"{MAX_CONTENT_CHARS}"}, ensure_ascii=False))
                return 2
            turn = self._turn_number(project_id) + 1
            if turn > MAX_ROUNDS * 2:
                print(json.dumps({"error": "round_cap_reached",
                                  "max_rounds": MAX_ROUNDS},
                                 ensure_ascii=False))
                return 1
            res = self.adapter.send(site, text, project_id)
            if not res.get("ok"):
                if res.get("uncertain"):
                    self._set_status(project_id, "PAUSED_UNCERTAIN",
                                     detail=res.get("error", "timeout"))
                    print(json.dumps({
                        "status": "paused_uncertain",
                        "project_id": project_id,
                        "error": res.get("error"),
                        "instruction": "Send outcome unknown. Do NOT "
                                       "auto-resend; ask the user to confirm.",
                    }, ensure_ascii=False))
                    return 1
                if res.get("handoff"):
                    print(json.dumps({
                        "status": "handoff_needed",
                        "project_id": project_id,
                        "handoff": res["handoff"],
                        "instruction": "Native host / extension is not "
                                       "connected. Perform the send with a "
                                       "browser task, then run: "
                                       "record-send --project-id %s "
                                       "--message-id %s --outcome sent|failed "
                                       "--content-file <reply.txt>"
                                       % (project_id, res.get("message_id")),
                    }, ensure_ascii=False))
                    return 1
                print(json.dumps({"status": "send_failed",
                                  "error": res.get("error")},
                                 ensure_ascii=False))
                return 1
            file_log.append_record(self.log_path, {
                "kind": "message",
                "project_id": project_id,
                "message_id": res["message_id"],
                "nonce": res["nonce"],
                "sender": "muse",
                "turn_number": turn,
                "content": text,
                "status": "sent",
            })
            self._write_heartbeat(project_id, "DISCUSSING")
            print(json.dumps({
                "status": "sent",
                "project_id": project_id,
                "message_id": res["message_id"],
                "turn_number": turn,
                "next": "poll for ChatGPT's reply with: advance "
                        "--project-id %s" % project_id,
            }, ensure_ascii=False))
            return 0
        # 3. No reply file: poll for a new reply from ChatGPT.
        res = self.adapter.read_latest(site, project_id)
        if not res.get("ok"):
            if res.get("handoff"):
                print(json.dumps({
                    "status": "handoff_needed",
                    "project_id": project_id,
                    "handoff": res["handoff"],
                    "instruction": "Native host / extension is not "
                                   "connected. Read the latest reply with a "
                                   "browser task and record it with: "
                                   "advance --record-reply --reply-file "
                                   "<file-with-the-reply-text>",
                }, ensure_ascii=False))
                return 1
            print(json.dumps({"status": "read_failed",
                              "error": res.get("error")},
                             ensure_ascii=False))
            return 1
        if not res.get("found"):
            self._write_heartbeat(project_id, "DISCUSSING")
            print(json.dumps({"status": "waiting_for_reply",
                              "project_id": project_id,
                              "instruction": "No new reply yet. Run advance "
                                             "again later (poll)."},
                             ensure_ascii=False))
            return 0
        last = self._last_message(project_id, sender="chatgpt")
        if last and last.get("content_sha256") == res.get("content_sha256"):
            print(json.dumps({"status": "waiting_for_reply",
                              "project_id": project_id,
                              "detail": "latest reply already recorded"},
                             ensure_ascii=False))
            return 0
        turn = self._turn_number(project_id) + 1
        file_log.append_record(self.log_path, {
            "kind": "message",
            "project_id": project_id,
            "message_id": "m-" + (res.get("nonce") or secrets.token_hex(8)),
            "nonce": res.get("nonce"),
            "sender": res.get("sender", "chatgpt"),
            "origin": res.get("origin"),
            "turn_number": turn,
            "content": res["content"],
            "status": "received",
        })
        self._write_heartbeat(project_id, "DISCUSSING")
        print(json.dumps({
            "status": "next_round_needed",
            "project_id": project_id,
            "turn_number": turn,
            "sender": res.get("sender"),
            "origin": res.get("origin"),
            "content": res["content"],
            "instruction": "MODEL TASK (Muse session): read the reply above "
                           "and generate the next round's reply text "
                           "(Proposal / Objection / Evidence / Resolution). "
                           "Then run: advance --project-id %s --reply-file "
                           "<reply.txt>. run.py does NOT generate reply text."
                           % project_id,
            "honesty": HONESTY_BLOCK["muse_handoff_auto_wake"],
        }, ensure_ascii=False))
        return 0

    def record_send(self, project_id, message_id, outcome, content_file=None):
        """Record the outcome of a browser-task send (handoff completion).

        The Muse session performed the send with a browser task because the
        native host / extension was not connected. This completes the send
        transaction that adapter.send() opened with send_intent.
        outcome: "sent" | "failed" | "unknown" (unknown -> UNCERTAIN, pause).
        """
        if self._project(project_id) is None:
            print(json.dumps({"error": "project_not_found"},
                             ensure_ascii=False))
            return 1
        res = self.adapter.record_browser_result(message_id, outcome)
        if outcome == "sent" and content_file:
            try:
                with open(content_file, "r", encoding="utf-8") as f:
                    text = f.read()
            except OSError as e:
                print(json.dumps(
                    {"error": f"cannot read content file: {e}"},
                    ensure_ascii=False))
                return 2
            turn = self._turn_number(project_id) + 1
            file_log.append_record(self.log_path, {
                "kind": "message",
                "project_id": project_id,
                "message_id": message_id,
                "sender": "muse",
                "turn_number": turn,
                "content": text,
                "status": "sent",
            })
            self._write_heartbeat(project_id, "DISCUSSING")
        print(json.dumps({"status": "recorded",
                          "project_id": project_id,
                          "message_id": message_id,
                          "outcome": res.get("outcome")},
                         ensure_ascii=False))
        return 0 if res.get("ok") else 1

    def resume(self, project_id):
        project = self._project(project_id)
        if project is None:
            print(json.dumps({"error": "project_not_found",
                              "project_id": project_id}, ensure_ascii=False))
            return 1
        # FIX 2: a terminal project cannot be resumed.
        if self._is_terminal(project):
            print(json.dumps({"error": "project_closed",
                              "status": project.get("status"),
                              "project_id": project_id},
                             ensure_ascii=False))
            return 1
        uncertain = file_log.list_uncertain(self.log_path)
        mine = [r for r in uncertain
                if r.get("message_id") in
                {rec.get("message_id") for rec in
                 self._project_records(project_id)}]
        if mine:
            print(json.dumps({
                "status": "paused_uncertain",
                "project_id": project_id,
                "uncertain": [r.get("message_id") for r in mine],
                "instruction": "Still UNCERTAIN. Do NOT auto-resend. Ask "
                               "the user to confirm whether each message "
                               "arrived; then record the outcome with "
                               "file_log send-confirm (sent/failed).",
            }, ensure_ascii=False))
            return 1
        ok, unc = self._reconcile_or_pause(project_id)
        if not ok:
            print(json.dumps({"status": "paused_uncertain",
                              "uncertain": unc}, ensure_ascii=False))
            return 1
        # FIX 2: resume writes the new state into the log, so the
        # merged _project() status moves out of PAUSED (a resume that
        # wrote nothing would leave advance() refusing forever).
        self._set_status(project_id, "DISCUSSING", detail="resumed")
        print(json.dumps({"status": "resumed",
                          "project_id": project_id,
                          "turn_number": self._turn_number(project_id),
                          "next": "advance --project-id %s" % project_id},
                         ensure_ascii=False))
        return 0

    def reconcile(self, project_id):
        result = file_log.reconcile(
            self.log_path,
            verify_fn=lambda mid: self.adapter.verify(mid))
        print(json.dumps({"project_id": project_id, **result},
                         ensure_ascii=False))
        return 0 if not result["uncertain"] else 1

    def pause(self, project_id, reason=""):
        project = self._project(project_id)
        if project is None:
            print(json.dumps({"error": "project_not_found"},
                             ensure_ascii=False))
            return 1
        # FIX 2: a terminal project cannot be paused back to life.
        if self._is_terminal(project):
            print(json.dumps({"error": "project_closed",
                              "status": project.get("status"),
                              "project_id": project_id},
                             ensure_ascii=False))
            return 1
        self._set_status(project_id, "PAUSED", detail=reason)
        print(json.dumps({"status": "paused", "project_id": project_id,
                          "reason": reason}, ensure_ascii=False))
        return 0

    def complete(self, project_id, reason=""):
        project = self._project(project_id)
        if project is None:
            print(json.dumps({"error": "project_not_found"},
                             ensure_ascii=False))
            return 1
        # FIX 2: completing an already-terminal project is a refusal,
        # not a state flip.
        if self._is_terminal(project):
            print(json.dumps({"error": "project_closed",
                              "status": project.get("status"),
                              "project_id": project_id},
                             ensure_ascii=False))
            return 1
        self._set_status(project_id, "COMPLETED", detail=reason)
        print(json.dumps({"status": "completed", "project_id": project_id,
                          "reason": reason}, ensure_ascii=False))
        return 0

    # -- two modes: discussion (default) vs execution (gated) ---------------

    def set_mode(self, project_id, mode):
        if self._project(project_id) is None:
            print(json.dumps({"error": "project_not_found"},
                             ensure_ascii=False))
            return 1
        if mode not in MODES:
            print(json.dumps({"error": "bad_mode", "mode": mode,
                              "allowed": list(MODES)}, ensure_ascii=False))
            return 2
        file_log.append_record(self.log_path, {
            "kind": "project_mode",
            "project_id": project_id,
            "mode": mode,
        })
        print(json.dumps({
            "status": "mode_set",
            "project_id": project_id,
            "mode": mode,
            "note": ("execution mode: every operation still needs a "
                     "local-approval-page approval (approvals.py gate); "
                     "the Muse approval card cannot authorize execution "
                     "in RC4; switching modes alone approves nothing.")
            if mode == "execution" else
            "discussion mode: no externally-effective operations.",
        }, ensure_ascii=False))
        return 0

    def execute(self, project_id, decision_id, operation_id, params_file):
        """Run one externally-effective operation (Execution mode only).

        Default-deny: refused unless (1) the project is in execution
        mode AND (2) approvals.check_execution() allows this exact
        decision + operation + params digest. check_execution re-reads
        the whole approval record from the store at execution time
        (still approved, not revoked/expired, option still offered,
        params digest still matching, channel still local_approval_page,
        never executed before) — it never trusts what a UI displayed.
        The operation whitelist currently contains only write_file
        (write a summary file inside this project's directory).
        """
        if self._project(project_id) is None:
            print(json.dumps({"error": "project_not_found"},
                             ensure_ascii=False))
            return 1
        if self._mode(project_id) != "execution":
            print(json.dumps({
                "status": "refused",
                "reason": "mode_is_discussion",
                "project_id": project_id,
                "instruction": "This project is in Discussion mode, which "
                               "performs no externally-effective operations. "
                               "Switch with: set-mode --project-id %s "
                               "--mode execution (then every operation still "
                               "needs a local-approval-page approval)."
                               % project_id,
            }, ensure_ascii=False))
            return 1
        try:
            with open(params_file, "r", encoding="utf-8") as f:
                params = json.load(f)
        except (OSError, ValueError) as e:
            print(json.dumps({"error": f"cannot read params file: {e}"},
                             ensure_ascii=False))
            return 2
        if not isinstance(params, dict):
            print(json.dumps({"error": "params must be a JSON object"},
                             ensure_ascii=False))
            return 2
        params_digest = _appr_sha256(_canonical(params))
        allowed, reason = self.approval_store.check_execution(
            decision_id, operation_id, params_digest)
        if not allowed:
            print(json.dumps({"status": "refused", "reason": reason,
                              "decision_id": decision_id,
                              "operation_id": operation_id},
                             ensure_ascii=False))
            return 1
        action = params.get("action")
        if action not in EXECUTION_WHITELIST:
            print(json.dumps({"status": "refused",
                              "reason": "operation_not_whitelisted",
                              "action": action,
                              "whitelist": list(EXECUTION_WHITELIST)},
                             ensure_ascii=False))
            return 1
        if action == "write_file":
            return self._execute_write_file(project_id, decision_id,
                                            operation_id, params,
                                            params_digest)
        return 1

    def _execute_write_file(self, project_id, decision_id, operation_id,
                            params, params_digest):
        """Whitelisted op: write a text file inside this project's own
        directory. The path must be relative and stay inside the
        project directory (no '..', no absolute path)."""
        rel = params.get("path", "")
        content = params.get("content", "")
        if not isinstance(rel, str) or not rel or os.path.isabs(rel):
            print(json.dumps({"status": "refused",
                              "reason": "bad_path", "path": rel},
                             ensure_ascii=False))
            return 1
        if not isinstance(content, str):
            print(json.dumps({"status": "refused",
                              "reason": "bad_content"}, ensure_ascii=False))
            return 1
        if len(content) > MAX_CONTENT_CHARS:
            print(json.dumps({"status": "refused",
                              "reason": "content_too_long",
                              "chars": len(content),
                              "max": MAX_CONTENT_CHARS}, ensure_ascii=False))
            return 1
        project_dir = os.path.join(self.state_dir, "projects", project_id)
        target = os.path.normpath(os.path.join(project_dir, rel))
        if os.path.commonpath([project_dir, target]) != project_dir:
            print(json.dumps({"status": "refused",
                              "reason": "path_escapes_project_dir",
                              "path": rel}, ensure_ascii=False))
            return 1
        os.makedirs(os.path.dirname(target) or project_dir, exist_ok=True)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
        file_log.append_record(self.log_path, {
            "kind": "execution",
            "project_id": project_id,
            "decision_id": decision_id,
            "operation_id": operation_id,
            "operation_params_digest": params_digest,
            "action": "write_file",
            "path": rel,
            "content_sha256": _sha256(content),
        })
        print(json.dumps({"status": "executed",
                          "project_id": project_id,
                          "decision_id": decision_id,
                          "operation_id": operation_id,
                          "action": "write_file",
                          "path": target}, ensure_ascii=False))
        return 0

    def status(self, project_id=None):
        out = {"honesty": HONESTY_BLOCK}
        if project_id:
            project = self._project(project_id)
            if project is None:
                print(json.dumps({"error": "project_not_found"},
                                 ensure_ascii=False))
                return 1
            beat, code = watchdog.check(self.heartbeat_path, 600)
            exe_path = os.path.join(self.skill_root, "transport",
                                    "agent-relay-host.exe")
            out.update({
                "project_id": project_id,
                "topic": project.get("topic"),
                "status": project.get("status"),
                "mode": self._mode(project_id),
                "turn_number": self._turn_number(project_id),
                "max_rounds": project.get("max_rounds", MAX_ROUNDS),
                "records": len(self._project_records(project_id)),
                "uncertain_sends": [
                    r.get("message_id")
                    for r in file_log.list_uncertain(self.log_path)],
                "watchdog": beat,
                "native_host_connected":
                    self.adapter.native_host_connected(),
                "windows_host_exe": {
                    "present": os.path.exists(exe_path),
                    "path": exe_path,
                    "note": ("Real .exe launcher (mingw-w64 cross-compile, "
                             "PE32+ GUI). It has NOT been run on a real "
                             "Windows machine — Windows E2E stays PENDING "
                             "until a real-Chrome round trip is verified.")
                    if os.path.exists(exe_path) else
                    "agent-relay-host.exe is missing from transport/.",
                },
            })
        else:
            projects = {}
            for rec in self._records():
                if rec.get("kind") == "project":
                    projects[rec["project_id"]] = rec.get("topic")
            out["projects"] = projects
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Agent Relay orchestrator entry (run.py)")
    parser.add_argument("--skill-root", required=True)
    parser.add_argument("--mode", default="native_host",
                        choices=["native_host", "browser_task"])
    sub = parser.add_subparsers(dest="command", required=True)
    p_create = sub.add_parser("create")
    p_create.add_argument("--topic", required=True)
    p_create.add_argument("--project-id", default=None)
    p_create.add_argument("--mode", default="discussion",
                          choices=list(MODES))
    p_adv = sub.add_parser("advance")
    p_adv.add_argument("--project-id", required=True)
    p_adv.add_argument("--reply-file", default=None)
    p_adv.add_argument("--site", default="chatgpt")
    p_res = sub.add_parser("resume")
    p_res.add_argument("--project-id", required=True)
    p_recsend = sub.add_parser("record-send")
    p_recsend.add_argument("--project-id", required=True)
    p_recsend.add_argument("--message-id", required=True)
    p_recsend.add_argument("--outcome", required=True,
                           choices=["sent", "failed", "unknown"])
    p_recsend.add_argument("--content-file", default=None)
    p_rec = sub.add_parser("reconcile")
    p_rec.add_argument("--project-id", required=True)
    p_pause = sub.add_parser("pause")
    p_pause.add_argument("--project-id", required=True)
    p_pause.add_argument("--reason", default="")
    p_comp = sub.add_parser("complete")
    p_comp.add_argument("--project-id", required=True)
    p_comp.add_argument("--reason", default="")
    p_status = sub.add_parser("status")
    p_status.add_argument("--project-id", default=None)
    p_setmode = sub.add_parser("set-mode")
    p_setmode.add_argument("--project-id", required=True)
    p_setmode.add_argument("--mode", required=True, choices=list(MODES))
    p_exec = sub.add_parser("execute")
    p_exec.add_argument("--project-id", required=True)
    p_exec.add_argument("--decision-id", required=True)
    p_exec.add_argument("--operation-id", required=True)
    p_exec.add_argument("--params-file", required=True)
    args = parser.parse_args(argv)
    runner = Runner(args.skill_root, mode=args.mode)
    if args.command == "create":
        return runner.create(args.topic, args.project_id, args.mode)
    if args.command == "advance":
        return runner.advance(args.project_id, args.reply_file, args.site)
    if args.command == "resume":
        return runner.resume(args.project_id)
    if args.command == "record-send":
        return runner.record_send(args.project_id, args.message_id,
                                  args.outcome, args.content_file)
    if args.command == "reconcile":
        return runner.reconcile(args.project_id)
    if args.command == "pause":
        return runner.pause(args.project_id, args.reason)
    if args.command == "complete":
        return runner.complete(args.project_id, args.reason)
    if args.command == "set-mode":
        return runner.set_mode(args.project_id, args.mode)
    if args.command == "execute":
        return runner.execute(args.project_id, args.decision_id,
                              args.operation_id, args.params_file)
    if args.command == "status":
        return runner.status(args.project_id)
    return 2


if __name__ == "__main__":
    sys.exit(main())
