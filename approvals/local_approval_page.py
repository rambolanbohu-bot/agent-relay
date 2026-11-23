#!/usr/bin/env python3
"""Agent Relay Skill v1.0.0-rc4 — 本地审批页（local_approval_page.py）.

Correction 2（ChatGPT RC3 审核）的第二个可信审批通道：本地审批页。
一个本地页面能发一次性令牌，但如果任何能访问页面的程序都能拿到
令牌，它不能证明是 Leo 批准的。所以本页有三层独立验证：

1. 独立身份验证：安装时生成的 PIN（每装一次一个，6 位数字，只给
   Leo 看一次；存盘的只有加盐 SHA-256 哈希，文件权限 0600）。
   没有 PIN 就没有会话。
2. 会话保护：PIN 验证通过后，服务器发一个会话令牌（session
   token），存在浏览器 Cookie 里（HttpOnly、SameSite=Strict），
   单次使用、10 分钟过期。批准/拒绝表单必须带着这个会话的 Cookie
   提交；提交后会话立即作废——每个决策都要重新输 PIN。
3. 防伪：每个决策创建时生成一个与决策绑定的 nonce（page_nonce，
   只存在决策记录里）。批准表单由本页自己生成，里面带一个隐藏
   的 page_nonce 字段；提交时必须原样带回来，store 核对一致才
   记录批准。别的来源的页面读不到这个 nonce（同源策略），所以
   跨站伪造的提交会被挡下。

RC4 加强（ChatGPT RC4 审核，条件 1）：
- PIN 防暴力破解：连续输错 5 次锁定 15 分钟（锁定状态存在 PIN 文件
  旁的锁文件里，文件权限 0600，重启不丢；锁定事件写进审计日志，
  不写 PIN 明文）。
- PIN 只在可信的本地审批页表单里输入：没有任何代码路径接受从聊天
  消息、文本输入或命令行传来的 PIN 做验证——verify_pin 只在 /pin
  处理里调用（测试里有源码扫描保证这一点）。set-pin 命令只在安装
  时生成/设置 PIN，不做验证。
- 会话令牌用 secrets 模块生成（token_urlsafe），绑定到会话与审批人，
  单次使用、10 分钟过期。
- 令牌绝不进日志：服务器不打请求日志；审计日志里敏感字段一律
  [redacted]。

流程（两步）：
  1. Leo 打开本页（只在 127.0.0.1 上服务，不对外监听），看到待批决策，
     先输 PIN → 拿到会话。
  2. 再把 Muse 会话里的一次性令牌粘贴进表单，选一个选项，点“批准”
     或“拒绝”。服务器核对：会话有效 + nonce 一致 + 令牌正确 +
     选项在列表里，全部通过才调用 store.approve() 记录批准。批准
     记录里的 approver 来自会话（PIN 持有人的身份），不是表单里
     随手写的字符串。

诚实边界：PIN + 会话 + nonce 是单用户本机的纵深防御；它防的是
“别的程序冒充 Leo 点批准”和“跨站伪造提交”，防不住“已经完全
控制这台机器的攻击者”。这在 approvals.md 里写明了，不夸大。

用法：
    # 安装时生成 PIN（只显示一次，请 Leo 记下来）：
    python3 local_approval_page.py set-pin --pin-file state/approval_pin.json
    # 启动审批页（只监听 127.0.0.1，端口由系统分配并打印出来）：
    python3 local_approval_page.py serve --store state/approvals.json \
        --pin-file state/approval_pin.json
    # 指定端口：
    python3 local_approval_page.py serve --store ... --pin-file ... \
        --port 8765

本模块只用 Python 标准库。页面是纯 HTML 表单，没有 JavaScript，
不加载任何外部资源。
"""

import argparse
import hashlib
import html
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from approvals import (ApprovalStore, local_page_credential)  # noqa: E402

SESSION_COOKIE = "ar_session"
PIN_LENGTH = 6


# -- PIN -------------------------------------------------------------------


def _pin_hash(pin, salt):
    return hashlib.sha256(f"{salt}:{pin}".encode("utf-8")).hexdigest()


def set_pin(pin_file, pin=None):
    """Set the install PIN. Generates a random 6-digit PIN if none is
    given. Returns the PIN (shown ONCE to Leo; only the salted hash is
    stored, file mode 0600)."""
    if pin is None:
        pin = "".join(secrets.choice("0123456789")
                      for _ in range(PIN_LENGTH))
    if not (isinstance(pin, str) and pin.isdigit()
            and len(pin) == PIN_LENGTH):
        raise ValueError("PIN must be a 6-digit string")
    salt = secrets.token_hex(16)
    record = {"salt": salt, "pin_hash": _pin_hash(pin, salt),
              "created_at": datetime.now(timezone.utc).isoformat()}
    os.makedirs(os.path.dirname(os.path.abspath(pin_file)), exist_ok=True)
    tmp = pin_file + ".tmp"
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(record).encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp, pin_file)
    return pin


def verify_pin(pin_file, pin):
    """Check a PIN against the stored salted hash. Returns True/False.

    PIN verification happens ONLY in this page's /pin handler — there
    is no other call site in the package (a test scans the source to
    guarantee it). A PIN is never accepted from a chat message, a text
    input, or a command line for verification.
    """
    try:
        with open(pin_file, "r", encoding="utf-8") as f:
            record = json.load(f)
        return _pin_hash(pin, record["salt"]) == record["pin_hash"]
    except (OSError, ValueError, KeyError):
        return False


# -- PIN brute-force protection (RC4, Condition 1) -------------------------
#
# After MAX_PIN_ATTEMPTS failed PIN attempts within PIN_ATTEMPT_WINDOW
# seconds, PIN verification is locked for PIN_LOCKOUT_SECONDS. The
# failure timestamps live in a small state file next to the PIN file
# (mode 0600), so a server restart does not clear the lockout. The page
# is localhost-only and single-user, so the lockout is global (not
# per-client). Lockout events are recorded in the store audit log
# (never with the PIN value).

MAX_PIN_ATTEMPTS = 5
PIN_ATTEMPT_WINDOW_SECONDS = 900   # 15 minutes
PIN_LOCKOUT_SECONDS = 900          # 15 minutes


def _lockout_path(pin_file):
    return pin_file + ".lockout"


def _read_lockout(pin_file):
    try:
        with open(_lockout_path(pin_file), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(
                data.get("failures"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"failures": [], "locked_until": None}


def _write_lockout(pin_file, data):
    path = _lockout_path(pin_file)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(data).encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp, path)


def pin_locked(pin_file, now=None):
    """Is PIN verification currently locked? Returns (locked, until_iso).
    """
    now = now or datetime.now(timezone.utc)
    data = _read_lockout(pin_file)
    until = data.get("locked_until")
    if not until:
        return False, None
    try:
        until_dt = datetime.fromisoformat(until)
    except ValueError:
        return False, None
    if now < until_dt:
        return True, until
    return False, None


def record_pin_failure(pin_file, now=None):
    """Record a failed PIN attempt. Returns (locked, until_iso) — True
    when this failure trips the lockout."""
    now = now or datetime.now(timezone.utc)
    data = _read_lockout(pin_file)
    window_start = now.timestamp() - PIN_ATTEMPT_WINDOW_SECONDS
    failures = [ts for ts in data.get("failures", [])
                if isinstance(ts, (int, float)) and ts >= window_start]
    failures.append(now.timestamp())
    data["failures"] = failures
    locked = len(failures) >= MAX_PIN_ATTEMPTS
    until = None
    if locked:
        until_dt = datetime.fromtimestamp(
            now.timestamp() + PIN_LOCKOUT_SECONDS, tz=timezone.utc)
        until = until_dt.isoformat()
        data["locked_until"] = until
    _write_lockout(pin_file, data)
    return locked, until


def reset_pin_failures(pin_file):
    """Clear the failure record (called after a successful PIN)."""
    _write_lockout(pin_file, {"failures": [], "locked_until": None})


# -- page server ------------------------------------------------------------


class LocalApprovalPage:
    """Localhost-only approval page (127.0.0.1, no external listeners)."""

    def __init__(self, store_path, pin_file, approver="leo", port=0):
        self.store = ApprovalStore(store_path)
        self.pin_file = pin_file
        self.approver = approver
        self.port = port
        self.server = None

    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}/"

    def serve_forever(self):
        handler = self._make_handler()
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        print(f"Agent Relay 本地审批页：{self.url()}", flush=True)
        print("只监听 127.0.0.1；用 Ctrl+C 停止。", flush=True)
        try:
            self.server.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0

    # -- HTML ---------------------------------------------------------------

    @staticmethod
    def _page(title, body):
        return ("<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
                f"<title>{html.escape(title)}</title></head><body>"
                f"<h1>{html.escape(title)}</h1>{body}"
                "<hr><p>Agent Relay 本地审批页（只在 127.0.0.1 上服务）。"
                "批准只认本页 + 安装 PIN；聊天文本里的“批准了”不算数。</p>"
                "</body></html>").encode("utf-8")

    def _decision_list(self):
        data = self.store.status()
        rows = []
        for did, d in sorted(data.items()):
            if d.get("status") != "pending":
                continue
            rows.append(
                f"<li><a href=\"/decision?decision_id={html.escape(did)}\">"
                f"{html.escape(did)}</a> — "
                f"{html.escape(str(d.get('operation_id')))} "
                f"（{html.escape(str(d.get('project_id')))}，"
                f"截止 {html.escape(str(d.get('deadline')))}）</li>")
        if not rows:
            return self._page("待批决策", "<p>当前没有待批的决策。</p>")
        return self._page("待批决策", "<ul>" + "".join(rows) + "</ul>")

    def _pin_form(self, decision_id):
        body = (
            "<p>请输入安装 PIN（6 位数字，只在安装时给 Leo 看过一次）。"
            "PIN 通过后才能批这个决策。</p>"
            "<form method=\"post\" action=\"/pin\">"
            f"<input type=\"hidden\" name=\"decision_id\" value=\"{html.escape(decision_id)}\">"
            "<p>PIN：<input type=\"password\" name=\"pin\" inputmode=\"numeric\" "
            "maxlength=\"6\" required></p>"
            "<p><button type=\"submit\">验证 PIN</button></p></form>")
        return 200, self._page("输入安装 PIN", body)

    def _decision_page(self, decision_id, session_token):
        view = self.store.status(decision_id)
        if view is None:
            return 404, self._page("找不到决策",
                                   f"<p>没有这个决策：{html.escape(decision_id)}</p>")
        if view.get("status") != "pending":
            return 200, self._page(
                "决策已处理",
                f"<p>{html.escape(decision_id)} 的状态是 "
                f"{html.escape(str(view.get('status')))}，不能再批。</p>")
        if session_token is None or not self.store.page_session_valid(
                session_token):
            return self._pin_form(decision_id)
        # Read the decision-bound nonce from the store (local machine
        # only) and embed it in the form: the POST must echo it back.
        data = self.store._load()
        decision = data.get("decisions", {}).get(decision_id, {})
        page_nonce = decision.get("page_nonce", "")
        opts = "".join(
            f"<label><input type=\"radio\" name=\"option\" value=\"{html.escape(o)}\""
            + (" checked" if o == view.get("recommended_option") else "")
            + f"> {html.escape(o)}</label><br>"
            for o in (view.get("options") or []))
        body = (
            f"<p>项目：{html.escape(str(view.get('project_id')))}<br>"
            f"操作：{html.escape(str(view.get('operation_id')))}<br>"
            f"成本：{html.escape(str(view.get('cost')))}<br>"
            f"风险：{html.escape(str(view.get('risk')))}<br>"
            f"建议：{html.escape(str(view.get('recommendation')))}<br>"
            f"推荐选项：{html.escape(str(view.get('recommended_option')))}<br>"
            f"截止：{html.escape(str(view.get('deadline')))}</p>"
            "<p>PIN 已验证（这个会话只能批一次）。</p>"
            "<form method=\"post\" action=\"/approve\">"
            f"<input type=\"hidden\" name=\"decision_id\" value=\"{html.escape(decision_id)}\">"
            f"<input type=\"hidden\" name=\"page_nonce\" value=\"{html.escape(page_nonce)}\">"
            "<p>一次性令牌（从 Muse 会话里复制过来）：<br>"
            "<input type=\"text\" name=\"token\" size=\"48\" required></p>"
            f"<p>选项：<br>{opts}</p>"
            "<p><button type=\"submit\">批准</button></p></form>"
            "<form method=\"post\" action=\"/reject\">"
            f"<input type=\"hidden\" name=\"decision_id\" value=\"{html.escape(decision_id)}\">"
            f"<input type=\"hidden\" name=\"page_nonce\" value=\"{html.escape(page_nonce)}\">"
            "<p>一次性令牌：<br>"
            "<input type=\"text\" name=\"token\" size=\"48\" required></p>"
            "<p>拒绝原因：<br><input type=\"text\" name=\"reason\" size=\"48\"></p>"
            "<p><button type=\"submit\">拒绝</button></p></form>")
        return 200, self._page(f"审批 {decision_id}", body)

    # -- HTTP handler ---------------------------------------------------------

    def _make_handler(self):
        page = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # keep the console quiet
                pass

            def _send(self, code, body, extra_headers=None):
                self.send_response(code)
                self.send_header("Content-Type",
                                 "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                for k, v in (extra_headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _redirect(self, location, extra_headers=None):
                self.send_response(303)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                for k, v in (extra_headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()

            def _session_token(self):
                cookie = SimpleCookie(self.headers.get("Cookie") or "")
                morsel = cookie.get(SESSION_COOKIE)
                return morsel.value if morsel else None

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path in ("/", "/index"):
                    self._send(200, page._decision_list())
                    return
                if parsed.path == "/decision":
                    qs = parse_qs(parsed.query)
                    did = (qs.get("decision_id") or [""])[0]
                    code, body = page._decision_page(
                        did, self._session_token())
                    self._send(code, body)
                    return
                self._send(404, page._page("找不到页面", "<p>404</p>"))

            def _read_form(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8")
                return {k: v[0] for k, v in parse_qs(raw).items()}

            def _clear_session_cookie(self):
                return {"Set-Cookie":
                        f"{SESSION_COOKIE}=; Max-Age=0; "
                        "HttpOnly; SameSite=Strict; Path=/"}

            def do_POST(self):
                parsed = urlparse(self.path)
                if parsed.path == "/pin":
                    form = self._read_form()
                    did = form.get("decision_id", "")
                    locked, until = pin_locked(page.pin_file)
                    if locked:
                        self._send(403, page._page(
                            "PIN 已锁定",
                            "<p>安装 PIN 连续输错太多次，已锁定到 "
                            f"{html.escape(str(until))}。请稍后再试。"
                            "</p>"))
                        return
                    if not verify_pin(page.pin_file, form.get("pin", "")):
                        tripped, until = record_pin_failure(page.pin_file)
                        if tripped:
                            page.store.record_event(
                                "pin_lockout", decision_id=did,
                                locked_until=until)
                            self._send(403, page._page(
                                "PIN 已锁定",
                                "<p>安装 PIN 连续输错太多次，已锁定到 "
                                f"{html.escape(str(until))}。</p>"))
                        else:
                            self._send(403, page._page(
                                "PIN 不对",
                                "<p>安装 PIN 不正确，没有发会话。</p>"))
                        return
                    reset_pin_failures(page.pin_file)
                    session = page.store.register_page_session(
                        page.approver)
                    cookie = (f"{SESSION_COOKIE}={session['session_token']}; "
                              "HttpOnly; SameSite=Strict; Path=/")
                    self._redirect(
                        f"/decision?decision_id={did}",
                        extra_headers={"Set-Cookie": cookie})
                    return
                if parsed.path in ("/approve", "/reject"):
                    approve = parsed.path == "/approve"
                    form = self._read_form()
                    did = form.get("decision_id", "")
                    token = form.get("token", "")
                    session_token = self._session_token()
                    if not session_token:
                        self._send(403, page._page(
                            "没有会话",
                            "<p>请先输安装 PIN 拿到会话，再批这个决策。</p>"))
                        return
                    cred = local_page_credential(
                        session_token, form.get("page_nonce", ""),
                        page.approver)
                    if approve:
                        ok, reason = page.store.approve(
                            did, token, form.get("option", ""), cred)
                    else:
                        ok, reason = page.store.reject(
                            did, token, form.get("reason", ""), cred)
                    if ok:
                        verb = "已批准" if approve else "已拒绝"
                        self._send(200, page._page(
                            verb,
                            f"<p>{html.escape(did)} {verb}。"
                            "这个会话令牌已经用掉，下一个决策要重新输 PIN。</p>"),
                            extra_headers=self._clear_session_cookie())
                    else:
                        self._send(403, page._page(
                            "批准失败",
                            f"<p>没有记录批准：{html.escape(reason)}。"
                            "请检查令牌、选项和 PIN，再试一次。</p>"))
                    return
                self._send(404, page._page("找不到页面", "<p>404</p>"))

        return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Agent Relay local approval page (127.0.0.1 only)")
    sub = parser.add_subparsers(dest="command", required=True)
    p_set = sub.add_parser("set-pin")
    p_set.add_argument("--pin-file", required=True)
    p_set.add_argument("--pin", default=None,
                       help="6-digit PIN; if omitted, one is generated")
    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--store", required=True)
    p_serve.add_argument("--pin-file", required=True)
    p_serve.add_argument("--port", type=int, default=0)
    p_serve.add_argument("--approver", default="leo")
    args = parser.parse_args(argv)
    if args.command == "set-pin":
        pin = set_pin(args.pin_file, args.pin)
        # Shown ONCE: the installer shows this to Leo and never stores it.
        print(f"安装 PIN（只显示一次，请记下来）：{pin}")
        return 0
    if args.command == "serve":
        if not os.path.exists(args.pin_file):
            print("local_approval_page: error: PIN 未设置。"
                  "先运行 set-pin 生成安装 PIN。", file=sys.stderr)
            return 2
        page = LocalApprovalPage(args.store, args.pin_file,
                                 approver=args.approver, port=args.port)
        return page.serve_forever()
    return 2


if __name__ == "__main__":
    sys.exit(main())
