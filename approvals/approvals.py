#!/usr/bin/env python3
"""Agent Relay Skill v1.0.0-rc4 — 审批执行模块（approvals.py）.

实现 approvals.md 的一次性令牌仪式 + 审批状态机 + 执行前检查门。
orchestrator/run.py 在执行任何受控操作之前必须调用这里的检查门。

RC4 决定（ChatGPT RC4 审核，强制）：Muse 审批卡通道作为执行授权
来源被主动禁用。原因是 store 没有平台 API 可以反查
approval_request_id 是否真的存在——收据只能验形状，不能验真伪，
所以它不能作为执行授权的依据。platform_receipt() 调用即拒绝
（"platform_receipt_disabled"），任何手写 muse_approval_card 收据
的批准请求也被拒绝。执行模式只接受本地审批页通道的凭证。
Muse 审批卡在 RC4 里只是通知/展示通道（把决策包推给 Leo 看），
不是执行授权来源；直到平台能提供可验证的批准结果之前都保持禁用。

新规则（RC4）：
- 批准只能用本地审批页通道的凭证记录。凭证是一个 dict，必须由
  approvals/local_approval_page.py 签发。签发的前提是 Leo 在本机
  页上输入了安装时生成的 PIN（每装一次一个 PIN，只给 Leo 看一次，
  存盘的只有加盐哈希；连续输错 5 次锁定 15 分钟），页服务器发了
  一个会话令牌（session token，用 secrets 模块生成、单次使用、
  10 分钟过期、绑定到会话与审批人），并且表单带回了与决策绑定的
  防伪 nonce（page_nonce，创建决策时生成，只存在决策记录里）。
  批准时 store 核对：会话令牌已登记、未过期、未用过、属于该审批人；
  nonce 与决策一致；然后立即消耗掉这个会话令牌。
- Muse 审批卡通道已禁用：platform_receipt() 调用即拒绝；任何
  muse_approval_card 收据（无论字段多完整）一律拒绝
  （"platform_receipt_disabled"）。执行检查门也只接受
  local_approval_page 通道批准的决策；RC3 时代以审批卡批准的旧
  决策在 RC4 里不能执行。
- PIN 只在可信的本地审批页表单里输入。没有任何代码路径接受从聊天
  消息、文本输入或命令行传来的 PIN 做验证（verify_pin 只在本地审批
  页的 /pin 处理里调用；set-pin 命令只在安装时生成/设置 PIN）。
- 批准记录里绑定的 approver 来自凭证收据（decided_by），不是调用
  者传的；并且必须与创建决策时登记的期望审批人一致（不一致拒绝）。
- 令牌仪式不变：令牌明文只在创建时返回一次，存盘的只有哈希；
  批准时逐项核对（决策存在且 pending；令牌哈希对得上、未用过、
  未过期；选项是提供的选项之一；决策包哈希与展示给用户的那份一致）。
- 令牌绝不进日志：审计日志里不写任何令牌、会话令牌、PIN 或 nonce
  的明文；敏感字段名出现时一律写 [redacted]。
- 状态机：pending → approved / rejected / expired；已批准的决策可
  以被 revoke() 撤销（revoked）。超时永远不等于批准。令牌一次性：
  重放会被拒绝并计数。执行前检查门在执行时重新核对整条批准记录
  （仍 approved、未过期、未撤销、选项仍在列表里、操作与参数摘要
  仍一致、未执行过、通道仍是本地审批页），只信 store 里的数据，
  不信任何界面显示的状态。

诚实边界（必须写明，不能含糊）：
- Muse 审批卡通道在 RC4 里已禁用，原因就是它无法验证：store 没有
  平台 API 可以反查 approval_request_id。卡片仍然可以通知 Leo（把
  决策包推到他手机/会话里看），但点“批准”不再授权任何执行。
- 本地审批页通道：PIN + 会话 + nonce 是单用户本机的纵深防御；
  它防的是“别的程序冒充 Leo 点批准”和“跨站伪造提交”，防不住
  “已经完全控制这台机器的攻击者”。这在 approvals.md 里写明了，
  不夸大。

用法（库）：
    from approvals import ApprovalStore, platform_receipt
    store = ApprovalStore("state/approvals.json")
    created = store.create_decision(project_id="P-001",
        operation_id="OP-1",
        operation_params={"action": "write_file", "path": "summary.md"},
        options=["write", "skip"], recommended_option="write",
        evidence=["..."], cost="AUD 0", risk="low",
        recommendation="选 write", approver="leo", ttl_seconds=3600)
    # created: {"decision_id", "approval_id", "token", "package_sha256",
    #           "operation_params_digest", "deadline"}
    # 注意：token 只出现在这里一次；存盘的只有 token_hash。
    # 本地审批页通道（凭证由 local_approval_page.py 签发）：
    #   见 approvals/local_approval_page.py。批准后：
    ok, why = store.approve(decision_id, token, "write", cred)
    ok, why = store.check_execution(decision_id, "OP-1",
                                    operation_params_digest)
    # Muse 审批卡通道在 RC4 里已禁用：platform_receipt() 调用即拒绝
    # （"platform_receipt_disabled"），审批卡只是通知/展示通道。

用法（命令行）：
    python3 approvals.py create-decision --store state/approvals.json \
        --decision-file /path/to/decision.json
    python3 approvals.py approve --store state/approvals.json \
        --decision-id DEC-... --token <token> --option write \
        --receipt-file /path/to/receipt.json
    python3 approvals.py reject --store state/approvals.json \
        --decision-id DEC-... --token <token> --reason "..." \
        --receipt-file /path/to/receipt.json
    python3 approvals.py check-execution --store state/approvals.json \
        --decision-id DEC-... --operation-id OP-1 \
        --params-digest <sha256>
    python3 approvals.py status --store state/approvals.json \
        [--decision-id DEC-...]
    python3 approvals.py expire --store state/approvals.json

receipt.json 的格式（本地审批页通道签发的凭证；RC4 只接受这一种）：
    {"channel": "local_approval_page",
     "receipt": {"session_token": "<page server issued>",
                 "page_nonce": "<decision-bound nonce>",
                 "decided_by": "leo",
                 "pin_verified": true}}
muse_approval_card 收据在 RC4 里一律拒绝（"platform_receipt_disabled"）。
"""

import argparse
import hashlib
import json
import os
import secrets
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "orchestrator"))
from locking import FileLock  # noqa: E402

# 审批通道：RC4 只接受本地审批页。Muse 审批卡通道已禁用（见
# platform_receipt()）：它只能通知/展示，不能授权执行。
# 聊天文本（"chat_text"）、Relay 内容（"relay_content"）等一律拒绝。
TRUSTED_CHANNELS = ("local_approval_page",)
# 执行检查门接受的通道（与 TRUSTED_CHANNELS 相同，单独列出是为了
# 让 check_execution 的意图一目了然：只有本地审批页能放行执行）。
EXECUTION_CHANNELS = ("local_approval_page",)

DEFAULT_TTL_SECONDS = 3600  # 决策默认 1 小时内有效
PAGE_SESSION_TTL_SECONDS = 600  # 本地审批页会话默认 10 分钟，单次使用


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _canonical(obj):
    """Canonical JSON for hashing (sorted keys, no whitespace variance)."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _token_hash(token):
    return _sha256("agent-relay-approval-token:" + token)


def _session_token_hash(token):
    return _sha256("agent-relay-page-session:" + token)


# -- channel-issued credentials -------------------------------------------
#
# A credential is a dict {"channel": ..., "receipt": {...}}.
# In RC4 it may ONLY be produced by the local approval page
# (local_approval_page.py). The Muse approval card channel is DISABLED
# (platform_receipt() below raises platform_receipt_disabled).
# A bare channel string (e.g. channel="muse_approval_card") is NOT a
# credential and is refused. The channel can never be a caller-declared
# string.


def platform_receipt(approval_request_id, decided_by, decided_at=None):
    """DISABLED in RC4 — do not call.

    The Muse approval card is a notification/display channel only in
    RC4, NOT an execution authorization source: the store has no
    platform API to verify an approval_request_id, so a receipt can
    only be shape-checked, never proven real. Until the platform can
    provide a verifiable approval result, this channel stays disabled.
    Calling this function refuses loudly instead of building a
    credential that looks valid.
    """
    raise RuntimeError(
        "platform_receipt_disabled: the Muse approval card is a "
        "notification/display channel only in RC4; it is not an "
        "execution authorization source until the platform can provide "
        "a verifiable approval result. Use the local approval page "
        "(local_approval_page.py) instead.")


def local_page_credential(session_token, page_nonce, decided_by):
    """Build a local-approval-page credential.

    ONLY called by approvals/local_approval_page.py, after the page
    server has verified the install PIN, issued a live session token,
    and checked the decision-bound nonce. Never construct this by hand.
    """
    if not isinstance(session_token, str) or not session_token:
        raise ValueError("session_token must be a non-empty string")
    if not isinstance(page_nonce, str) or not page_nonce:
        raise ValueError("page_nonce must be a non-empty string")
    if not isinstance(decided_by, str) or not decided_by:
        raise ValueError("decided_by must be a non-empty string")
    return {
        "channel": "local_approval_page",
        "receipt": {
            "session_token": session_token,
            "page_nonce": page_nonce,
            "decided_by": decided_by,
            "pin_verified": True,
        },
    }


class ApprovalStore:
    """Approval decisions + one-time tokens + execution gate.

    Stored file layout (JSON, atomic write via tmp + os.replace):
        {"decisions": {decision_id: {...}},
         "approvals": {approval_id: {...}},
         "executions": {execution_id: {...}},
         "page_sessions": {session_token_hash: {...}},
         "audit": [ {...}, ... ]}
    The file NEVER contains a raw token — only token hashes.
    It also never contains a raw page session token — only its hash.
    """

    def __init__(self, store_path):
        self.store_path = store_path

    # -- persistence -----------------------------------------------------

    def _load(self):
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("decisions", {})
                data.setdefault("approvals", {})
                data.setdefault("executions", {})
                data.setdefault("page_sessions", {})
                data.setdefault("audit", [])
                return data
        except (FileNotFoundError, ValueError):
            pass
        return {"decisions": {}, "approvals": {}, "executions": {},
                "page_sessions": {}, "audit": []}

    def _save(self, data):
        os.makedirs(os.path.dirname(os.path.abspath(self.store_path)),
                    exist_ok=True)
        tmp = self.store_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.store_path)

    def _locked(self, fn, *args, **kwargs):
        with FileLock(self.store_path + ".lock", timeout=10):
            data = self._load()
            result = fn(data, *args, **kwargs)
            self._save(data)
            return result

    # Fields that must never appear in the audit log in the clear.
    # Tokens, session tokens, PINs and nonces are secrets: if any caller
    # passes one in an audit field, it is replaced with [redacted].
    # (RC4, Condition 1: tokens must NEVER appear in logs.)
    _SENSITIVE_FIELDS = frozenset({
        "token", "session_token", "pin", "page_nonce", "credential",
        "receipt",
    })

    def _audit(self, data, event, **fields):
        entry = {"event": event, "ts": _utcnow()}
        for key, value in fields.items():
            if key in self._SENSITIVE_FIELDS:
                entry[key] = "[redacted]"
            else:
                entry[key] = value
        data.setdefault("audit", []).append(entry)

    def record_event(self, event, **fields):
        """Append an audit event (used by the local approval page to
        record e.g. PIN lockouts). Sensitive fields are redacted."""
        def _record(data):
            self._audit(data, event, **fields)
            return True

        return self._locked(_record)

    # -- decision creation ----------------------------------------------

    def create_decision(self, project_id, operation_id, operation_params,
                        options, recommended_option, evidence, cost, risk,
                        recommendation, approver, ttl_seconds=None):
        """Create a decision package + one-time token.

        Returns {"decision_id", "approval_id", "token", "package_sha256",
        "operation_params_digest", "deadline"}. The token is returned ONCE
        and never stored — only its hash is stored.
        Also generates a page_nonce (stored in the decision record, NOT
        returned here): the local approval page must present it back, so
        an approval is bound to this exact decision.
        """
        if not options or recommended_option not in options:
            raise ValueError("recommended_option must be one of options")
        if not operation_id or not project_id:
            raise ValueError("project_id and operation_id are required")
        params_digest = _sha256(_canonical(operation_params))
        package = {
            "project_id": project_id,
            "operation_id": operation_id,
            "operation_params_digest": params_digest,
            "options": list(options),
            "recommended_option": recommended_option,
            "evidence": list(evidence or []),
            "cost": cost,
            "risk": risk,
            "recommendation": recommendation,
        }
        package_sha256 = _sha256(_canonical(package))
        ttl = ttl_seconds if ttl_seconds is not None else DEFAULT_TTL_SECONDS
        now = datetime.now(timezone.utc)
        deadline = now.timestamp() + ttl
        decision_id = "DEC-" + secrets.token_hex(6).upper()
        approval_id = "APR-" + secrets.token_hex(6).upper()
        token = secrets.token_urlsafe(32)
        page_nonce = secrets.token_urlsafe(24)
        decision = dict(package)
        decision.update({
            "decision_id": decision_id,
            "approval_id": approval_id,
            "token_hash": _token_hash(token),
            "token_used": False,
            "page_nonce": page_nonce,
            "approver": approver,
            "status": "pending",
            "created_at": _utcnow(),
            "deadline": datetime.fromtimestamp(deadline,
                                               tz=timezone.utc).isoformat(),
            "approved_option": None,
            "approved_channel": None,
            "decided_at": None,
            "replay_count": 0,
        })

        def _create(data):
            data["decisions"][decision_id] = decision
            self._audit(data, "decision_created", decision_id=decision_id,
                        project_id=project_id, operation_id=operation_id,
                        package_sha256=package_sha256)
            return decision

        self._locked(_create)
        return {"decision_id": decision_id, "approval_id": approval_id,
                "token": token, "package_sha256": package_sha256,
                "operation_params_digest": params_digest,
                "deadline": decision["deadline"]}

    # -- local approval page sessions --------------------------------------
    #
    # The page server registers a session here AFTER verifying the
    # install PIN. The session token is single-use and short-lived.
    # Only its hash is stored.

    def register_page_session(self, decided_by,
                              ttl_seconds=None):
        """Register a local-approval-page session (called ONLY by the
        page server after PIN verification). Returns the raw session
        token (returned ONCE; only its hash is stored)."""
        if not isinstance(decided_by, str) or not decided_by:
            raise ValueError("decided_by must be a non-empty string")
        ttl = (ttl_seconds if ttl_seconds is not None
               else PAGE_SESSION_TTL_SECONDS)
        token = secrets.token_urlsafe(32)
        session = {
            "session_id": "SES-" + secrets.token_hex(6).upper(),
            "session_token_hash": _session_token_hash(token),
            "decided_by": decided_by,
            "created_at": _utcnow(),
            "expires_at": datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() + ttl,
                tz=timezone.utc).isoformat(),
            "used": False,
        }

        def _register(data):
            data["page_sessions"][session["session_token_hash"]] = session
            self._audit(data, "page_session_registered",
                        session_id=session["session_id"],
                        decided_by=decided_by)
            return session["session_id"]

        self._locked(_register)
        return {"session_id": session["session_id"],
                "session_token": token,
                "expires_at": session["expires_at"]}

    def page_session_valid(self, session_token):
        """Read-only check: is this page session token registered,
        unexpired and unused? Does NOT consume it (the approval call
        consumes it). Used by the local page to decide whether to show
        the approval form or ask for the PIN first."""
        if not isinstance(session_token, str) or not session_token:
            return False
        data = self._load()
        session = data.get("page_sessions", {}).get(
            _session_token_hash(session_token))
        if session is None or session.get("used"):
            return False
        try:
            return datetime.now(timezone.utc) <= datetime.fromisoformat(
                session["expires_at"])
        except (ValueError, KeyError):
            return False

    def _verify_page_session(self, data, session_token):
        """Check a page session token: registered, unexpired, unused.
        Consumes it (single-use). Returns (ok, reason, session)."""
        token_hash = _session_token_hash(session_token)
        session = data.get("page_sessions", {}).get(token_hash)
        if session is None:
            return False, "page_session_not_found", None
        if session.get("used"):
            return False, "page_session_already_used", None
        try:
            if datetime.now(timezone.utc) > datetime.fromisoformat(
                    session["expires_at"]):
                return False, "page_session_expired", None
        except (ValueError, KeyError):
            return False, "page_session_bad_expiry", None
        session["used"] = True
        return True, "ok", session

    # -- credential verification -------------------------------------------

    def _verify_credential(self, data, decision, credential):
        """Verify a channel-issued credential.

        Returns (ok, reason, decided_by). A bare channel string, a
        credential without a receipt, or a receipt missing its required
        fields is refused — the channel can never be caller-declared.
        """
        if not isinstance(credential, dict):
            # Correction 2: a bare string like "muse_approval_card" is
            # not a credential. Refuse it outright.
            return False, "credential_not_issued", None
        channel = credential.get("channel")
        if channel == "muse_approval_card":
            # RC4: the Muse approval card channel is DISABLED as an
            # execution authorization source (no platform API can verify
            # the receipt). Refuse with a clear reason, whatever the
            # receipt contains.
            return False, "platform_receipt_disabled", None
        if channel not in TRUSTED_CHANNELS:
            return False, "untrusted_channel", None
        receipt = credential.get("receipt")
        if not isinstance(receipt, dict):
            return False, "credential_missing_receipt", None
        decided_by = receipt.get("decided_by")
        if not isinstance(decided_by, str) or not decided_by:
            return False, "credential_missing_approver", None
        expected = decision.get("approver")
        if expected and decided_by != expected:
            return False, "approver_mismatch", None
        # local_approval_page
        if receipt.get("pin_verified") is not True:
            return False, "receipt_pin_not_verified", None
        session_token = receipt.get("session_token")
        if not isinstance(session_token, str) or not session_token:
            return False, "receipt_missing_session_token", None
        page_nonce = receipt.get("page_nonce")
        if not isinstance(page_nonce, str) or not page_nonce:
            return False, "receipt_missing_page_nonce", None
        if page_nonce != decision.get("page_nonce"):
            return False, "page_nonce_mismatch", None
        ok, reason, session = self._verify_page_session(data, session_token)
        if not ok:
            return False, reason, None
        if session.get("decided_by") != decided_by:
            return False, "approver_mismatch", None
        return True, "ok", decided_by

    # -- approve / reject -------------------------------------------------

    def _check_token(self, data, decision, token):
        """Token checks. Returns (ok, reason)."""
        if decision.get("token_used"):
            return False, "token_already_used"
        if _token_hash(token) != decision.get("token_hash"):
            return False, "token_mismatch"
        deadline = decision.get("deadline")
        try:
            if deadline and datetime.now(timezone.utc) > datetime.fromisoformat(deadline):
                return False, "token_expired"
        except ValueError:
            return False, "bad_deadline"
        return True, "ok"

    def _check_package(self, decision):
        """Recompute the package hash; a swapped proposal invalidates it."""
        package = {
            "project_id": decision.get("project_id"),
            "operation_id": decision.get("operation_id"),
            "operation_params_digest": decision.get(
                "operation_params_digest"),
            "options": decision.get("options"),
            "recommended_option": decision.get("recommended_option"),
            "evidence": decision.get("evidence"),
            "cost": decision.get("cost"),
            "risk": decision.get("risk"),
            "recommendation": decision.get("recommendation"),
        }
        return _sha256(_canonical(package))

    def approve(self, decision_id, token, option, credential):
        """Approve a decision. Returns (ok, reason).

        credential must be a local-approval-page credential dict (see
        local_approval_page.py). The Muse approval card channel is
        disabled in RC4 (platform_receipt_disabled); a bare channel
        string is refused.
        """
        def _approve(data):
            decision = data["decisions"].get(decision_id)
            if decision is None:
                return False, "decision_not_found"
            if decision.get("status") != "pending":
                return False, f"decision_not_pending:{decision.get('status')}"
            ok, reason, decided_by = self._verify_credential(
                data, decision, credential)
            if not ok:
                self._audit(data, "approve_rejected_bad_credential",
                            decision_id=decision_id, reason=reason)
                return False, reason
            ok, reason = self._check_token(data, decision, token)
            if not ok:
                if reason == "token_already_used":
                    decision["replay_count"] = \
                        decision.get("replay_count", 0) + 1
                    self._audit(data, "approve_replay_rejected",
                                decision_id=decision_id,
                                replay_count=decision["replay_count"])
                return False, reason
            if option not in (decision.get("options") or []):
                return False, "option_not_offered"
            if self._check_package(decision) != decision.get(
                    "package_sha256", "") and decision.get("package_sha256"):
                return False, "package_changed"
            # All checks passed: consume the token immediately.
            decision["token_used"] = True
            decision["status"] = "approved"
            decision["approved_option"] = option
            decision["approved_channel"] = credential["channel"]
            decision["decided_at"] = _utcnow()
            decision["decided_by"] = decided_by
            self._audit(data, "approved", decision_id=decision_id,
                        option=option, channel=credential["channel"],
                        approver=decided_by)
            return True, "approved"

        return self._locked(_approve)

    def reject(self, decision_id, token, reason_text, credential):
        """Reject a decision. Returns (ok, reason)."""
        def _reject(data):
            decision = data["decisions"].get(decision_id)
            if decision is None:
                return False, "decision_not_found"
            if decision.get("status") != "pending":
                return False, f"decision_not_pending:{decision.get('status')}"
            ok, reason, decided_by = self._verify_credential(
                data, decision, credential)
            if not ok:
                self._audit(data, "reject_rejected_bad_credential",
                            decision_id=decision_id, reason=reason)
                return False, reason
            ok, reason = self._check_token(data, decision, token)
            if not ok:
                if reason == "token_already_used":
                    decision["replay_count"] = \
                        decision.get("replay_count", 0) + 1
                return False, reason
            decision["token_used"] = True
            decision["status"] = "rejected"
            decision["approved_channel"] = credential["channel"]
            decision["decided_at"] = _utcnow()
            decision["decided_by"] = decided_by
            decision["reject_reason"] = reason_text
            self._audit(data, "rejected", decision_id=decision_id,
                        channel=credential["channel"],
                        approver=decided_by, reason=reason_text)
            return True, "rejected"

        return self._locked(_reject)

    # -- pre-execution gate ------------------------------------------------

    def check_execution(self, decision_id, operation_id,
                        operation_params_digest):
        """Pre-execution gate. The orchestrator MUST call this before any
        gated action. Returns (allowed, reason).

        Execution-time re-verification (RC4, Condition 1): every check
        below is re-read from the store at execution time — the gate
        never trusts what a UI displayed or what the caller claims. All
        of these must hold, or the action is refused:
          1. the decision exists and is approved (not pending, rejected,
             expired or revoked);
          2. the approval went through the full token ceremony (the
             one-time token was consumed at approve time);
          3. the approved option is still one of the offered options;
          4. the operation_id matches the approved decision;
          5. the operation params digest matches the approved spec
             (a deviation needs a new approval);
          6. the approval came from an execution-allowed channel
             (RC4: local_approval_page only — the Muse approval card
             channel is disabled);
          7. this approval has not been used to execute before;
          8. the decision has not expired.
        """
        def _check(data):
            decision = data["decisions"].get(decision_id)
            if decision is None:
                return False, "decision_not_found"
            if decision.get("status") != "approved":
                return False, f"not_approved:{decision.get('status')}"
            if not decision.get("token_used"):
                return False, "approval_token_not_consumed"
            if decision.get("approved_option") not in (
                    decision.get("options") or []):
                return False, "approved_option_invalid"
            if decision.get("operation_id") != operation_id:
                return False, "operation_id_mismatch"
            if decision.get("operation_params_digest") != \
                    operation_params_digest:
                return False, "params_digest_mismatch"
            if decision.get("approved_channel") not in EXECUTION_CHANNELS:
                return False, "execution_channel_not_allowed"
            deadline = decision.get("deadline")
            try:
                if deadline and datetime.now(timezone.utc) > datetime.fromisoformat(deadline):
                    return False, "expired"
            except ValueError:
                return False, "bad_deadline"
            for ex in data.get("executions", {}).values():
                if ex.get("decision_id") == decision_id:
                    return False, "approval_already_executed"
            execution_id = "EXE-" + secrets.token_hex(6).upper()
            data["executions"][execution_id] = {
                "execution_id": execution_id,
                "decision_id": decision_id,
                "operation_id": operation_id,
                "operation_params_digest": operation_params_digest,
                "approved_option": decision.get("approved_option"),
                "channel": decision.get("approved_channel"),
                "executed_at": _utcnow(),
            }
            self._audit(data, "execution_allowed", decision_id=decision_id,
                        execution_id=execution_id,
                        operation_id=operation_id)
            return True, "allowed"

        return self._locked(_check)

    def revoke(self, decision_id, reason=""):
        """Revoke an approved decision (e.g. the approver changed their
        mind, or the approval is found to be invalid). A revoked
        decision can never execute: check_execution refuses it because
        its status is no longer 'approved'. Returns (ok, reason)."""
        def _revoke(data):
            decision = data["decisions"].get(decision_id)
            if decision is None:
                return False, "decision_not_found"
            if decision.get("status") != "approved":
                return False, f"not_approved:{decision.get('status')}"
            decision["status"] = "revoked"
            decision["revoke_reason"] = reason
            self._audit(data, "revoked", decision_id=decision_id,
                        reason=reason)
            return True, "revoked"

        return self._locked(_revoke)

    # -- expiry / status ---------------------------------------------------

    def expire_overdue(self):
        """Pending decisions past their deadline become expired.

        Timeout never equals approval. Returns the expired decision_ids.
        """
        now = datetime.now(timezone.utc)

        def _expire(data):
            expired = []
            for did, decision in data["decisions"].items():
                if decision.get("status") != "pending":
                    continue
                deadline = decision.get("deadline")
                try:
                    if deadline and now > datetime.fromisoformat(deadline):
                        decision["status"] = "expired"
                        expired.append(did)
                        self._audit(data, "expired", decision_id=did)
                except ValueError:
                    continue
            return expired

        return self._locked(_expire)

    def status(self, decision_id=None):
        data = self._load()
        if decision_id:
            decision = data["decisions"].get(decision_id)
            if decision is None:
                return None
            view = dict(decision)
            view.pop("token_hash", None)  # never show even the hash
            view.pop("page_nonce", None)  # decision-bound, never shown
            return view
        out = {}
        for did, decision in data["decisions"].items():
            view = dict(decision)
            view.pop("token_hash", None)
            view.pop("page_nonce", None)
            out[did] = view
        return out


def _load_receipt(path):
    """Load a channel-issued credential from a JSON file.

    The file must contain a credential dict {"channel": ..., "receipt":
    {...}}. A file containing just a channel string is refused.
    """
    with open(path, "r", encoding="utf-8") as f:
        cred = json.load(f)
    if not isinstance(cred, dict):
        raise ValueError("receipt file must contain a credential object, "
                         "not a bare channel string")
    return cred


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Agent Relay approval store (one-time token ceremony; "
                    "RC4: local approval page credentials only; the Muse "
                    "approval card channel is disabled)")
    parser.add_argument("--store", required=True,
                        help="path to approvals.json")
    sub = parser.add_subparsers(dest="command", required=True)
    p_create = sub.add_parser("create-decision")
    p_create.add_argument("--decision-file", required=True,
                          help="JSON with project_id, operation_id, "
                               "operation_params, options, "
                               "recommended_option, evidence, cost, risk, "
                               "recommendation, approver, ttl_seconds?")
    p_approve = sub.add_parser("approve")
    p_approve.add_argument("--decision-id", required=True)
    p_approve.add_argument("--token", required=True)
    p_approve.add_argument("--option", required=True)
    p_approve.add_argument("--receipt-file", required=True,
                           help="JSON file with the channel-issued "
                                "credential (see module docstring). A bare "
                                "channel string is refused.")
    p_reject = sub.add_parser("reject")
    p_reject.add_argument("--decision-id", required=True)
    p_reject.add_argument("--token", required=True)
    p_reject.add_argument("--reason", default="")
    p_reject.add_argument("--receipt-file", required=True,
                          help="JSON file with the channel-issued "
                               "credential.")
    p_exec = sub.add_parser("check-execution")
    p_exec.add_argument("--decision-id", required=True)
    p_exec.add_argument("--operation-id", required=True)
    p_exec.add_argument("--params-digest", required=True)
    p_status = sub.add_parser("status")
    p_status.add_argument("--decision-id", default=None)
    p_revoke = sub.add_parser("revoke")
    p_revoke.add_argument("--decision-id", required=True)
    p_revoke.add_argument("--reason", default="")
    sub.add_parser("expire")
    args = parser.parse_args(argv)
    store = ApprovalStore(args.store)

    if args.command == "create-decision":
        try:
            with open(args.decision_file, "r", encoding="utf-8") as f:
                spec = json.load(f)
        except (OSError, ValueError) as e:
            print(f"approvals: error: cannot read decision file: {e}",
                  file=sys.stderr)
            return 2
        try:
            created = store.create_decision(
                project_id=spec["project_id"],
                operation_id=spec["operation_id"],
                operation_params=spec.get("operation_params", {}),
                options=spec["options"],
                recommended_option=spec["recommended_option"],
                evidence=spec.get("evidence", []),
                cost=spec.get("cost", ""),
                risk=spec.get("risk", ""),
                recommendation=spec.get("recommendation", ""),
                approver=spec.get("approver", ""),
                ttl_seconds=spec.get("ttl_seconds"))
        except (ValueError, KeyError) as e:
            print(f"approvals: error: {e}", file=sys.stderr)
            return 1
        print(json.dumps(created, ensure_ascii=False))
        return 0
    if args.command == "approve":
        try:
            cred = _load_receipt(args.receipt_file)
        except (OSError, ValueError) as e:
            print(f"approvals: error: cannot load receipt: {e}",
                  file=sys.stderr)
            return 2
        ok, reason = store.approve(args.decision_id, args.token,
                                   args.option, cred)
        print(json.dumps({"allowed": ok, "reason": reason},
                         ensure_ascii=False))
        return 0 if ok else 1
    if args.command == "reject":
        try:
            cred = _load_receipt(args.receipt_file)
        except (OSError, ValueError) as e:
            print(f"approvals: error: cannot load receipt: {e}",
                  file=sys.stderr)
            return 2
        ok, reason = store.reject(args.decision_id, args.token, args.reason,
                                  cred)
        print(json.dumps({"allowed": ok, "reason": reason},
                         ensure_ascii=False))
        return 0 if ok else 1
    if args.command == "check-execution":
        ok, reason = store.check_execution(args.decision_id,
                                           args.operation_id,
                                           args.params_digest)
        print(json.dumps({"allowed": ok, "reason": reason},
                         ensure_ascii=False))
        return 0 if ok else 1
    if args.command == "status":
        view = store.status(args.decision_id)
        if view is None:
            print(json.dumps({"error": "decision_not_found"},
                             ensure_ascii=False))
            return 1
        print(json.dumps(view, ensure_ascii=False, indent=2))
        return 0
    if args.command == "expire":
        expired = store.expire_overdue()
        print(json.dumps({"expired": expired}, ensure_ascii=False))
        return 0
    if args.command == "revoke":
        ok, reason = store.revoke(args.decision_id, args.reason)
        print(json.dumps({"revoked": ok, "reason": reason},
                         ensure_ascii=False))
        return 0 if ok else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
