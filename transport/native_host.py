#!/usr/bin/env python3
"""Agent Relay Skill v1.0.0-rc4 — Native Messaging host (native_host.py).

条件 2（ChatGPT 验收条件）：扩展与协调器是两个不同的运行时；只写
出两边是不够的，必须有一条**可运行的连接**。本文件就是这条连接的
本机一端：Chrome Native Messaging host。

RC3 Correction 1：Chrome 的 host 清单 `path` 必须指向一个 .exe，
不能指向 .bat 或 .py。所以 Chrome 拉起的是
transport/agent-relay-host.exe（C 启动器，见
transport/native_host/），启动器再拉起本文件（python.exe
native_host.py）。本文件本身的逻辑没变；它不知道自己是被谁拉起的。

两条通道：
1. 扩展 ↔ 本 host：Chrome Native Messaging 协议——stdin/stdout 上的
   4 字节小端长度前缀 + UTF-8 JSON（Chrome 的标准格式）。
   Chrome 在扩展连接 native host 时拉起 agent-relay-host.exe；
   端口关闭（stdin 到 EOF）时本进程干净退出；下次连接再拉起。
2. 本 host ↔ orchestrator/run.py：本机文件队列（state 目录下）：
   - inbox.jsonl：run.py 写命令（send / read_latest / health / ping）。
   - outbox.jsonl：本 host 写结果（扩展回来的回复、发送结果、错误）。
   - 两个文件都是追加日志（审计用），本 host 用偏移文件记录已处理
     到 inbox 的第几行；重启后从偏移处继续，不丢、不重复。
   这样 run.py 与扩展之间不需要 socket；文件日志就是接口（带发送
   事务语义，见 orchestrator/file_log.py）。

认证（本地纵深防御）：run.py 首次运行时在 state 目录下生成一个
0600 权限的 secret 文件；写进 inbox 的每条命令必须带上这个 secret
（字段 "auth"）。本 host 逐条核对，secret 不对的命令直接丢弃并记
一条审计记录。注意：这防的是本机上别的进程冒充 run.py 写命令；
它不能代替用户审批（审批只认本地审批页；Muse 审批卡在 RC4 里只是通知/展示通道，不能授权执行）。

本 host 的权限边界：
- 只读写自己的 state 目录（inbox/outbox/offset/secret/heartbeat）。
- 不读任意文件，不执行系统命令，不释放审批。
- 从扩展收到的内容只当数据转发进 outbox，绝不执行。

用法：
    python3 native_host.py --state-dir /path/to/state/native_host
    # Chrome 用 Native Messaging 清单（transport/extension/
    # com.agentrelay.host.json）拉起本进程；stdin/stdout 走扩展通道。

测试：tests/test_native_host.py 用脚本模拟扩展那一端——拉起本进程，
发一条消息进 stdin，读回 stdout 的回复，并验证 inbox→扩展→outbox
的整条往返（见 tests/TEST-RECORDS-v2.md）。
"""

import argparse
import json
import os
import struct
import sys
import threading
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "orchestrator"))
from locking import FileLock  # noqa: E402

POLL_SECONDS = 0.5
HEARTBEAT_SECONDS = 30


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def read_message(stream):
    """Read one length-prefixed JSON message from a binary stream.

    Returns the decoded object, or None on EOF.
    """
    header = stream.read(4)
    if not header:
        return None
    if len(header) < 4:
        raise ValueError("truncated native message header")
    (length,) = struct.unpack("<I", header)
    if length > 10 * 1024 * 1024:
        raise ValueError(f"native message too large: {length} bytes")
    raw = stream.read(length)
    if len(raw) < length:
        raise ValueError("truncated native message body")
    return json.loads(raw.decode("utf-8"))


def write_message(stream, obj):
    """Write one length-prefixed JSON message to a binary stream."""
    raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    stream.write(struct.pack("<I", len(raw)))
    stream.write(raw)
    stream.flush()


def _load_secret(state_dir):
    """Read (or create) the local shared secret, mode 0600."""
    path = os.path.join(state_dir, "secret")
    if os.path.exists(path):
        with open(path, "r", encoding="ascii") as f:
            return f.read().strip()
    import secrets
    value = secrets.token_hex(32)
    os.makedirs(state_dir, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(fd, value.encode("ascii"))
    finally:
        os.close(fd)
    return value


class NativeHost:
    """Chrome Native Messaging host + file-queue bridge to run.py."""

    def __init__(self, state_dir, stdin=None, stdout=None):
        self.state_dir = state_dir
        self.inbox = os.path.join(state_dir, "inbox.jsonl")
        self.outbox = os.path.join(state_dir, "outbox.jsonl")
        self.offset_file = os.path.join(state_dir, "inbox.offset")
        self.heartbeat_file = os.path.join(state_dir, "heartbeat.json")
        self.secret = _load_secret(state_dir)
        self.stdin = stdin or sys.stdin.buffer
        self.stdout = stdout or sys.stdout.buffer
        self._stop = threading.Event()
        self._offset = self._read_offset()
        self._last_heartbeat = 0.0

    # -- file helpers ------------------------------------------------------

    def _read_offset(self):
        try:
            with open(self.offset_file, "r", encoding="ascii") as f:
                return int(f.read().strip() or "0")
        except (OSError, ValueError):
            return 0

    def _write_offset(self, value):
        tmp = self.offset_file + ".tmp"
        with open(tmp, "w", encoding="ascii") as f:
            f.write(str(value))
        os.replace(tmp, self.offset_file)

    def _append_outbox(self, record):
        record = dict(record)
        record.setdefault("ts", _utcnow())
        with FileLock(self.outbox + ".lock", timeout=10):
            with open(self.outbox, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())

    def _write_heartbeat(self):
        now = time.time()
        if now - self._last_heartbeat < HEARTBEAT_SECONDS:
            return
        self._last_heartbeat = now
        tmp = self.heartbeat_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "last_update": _utcnow(),
                       "status": "running"}, f)
        os.replace(tmp, self.heartbeat_file)

    # -- extension channel (stdin/stdout) -----------------------------------

    def _stdin_reader(self):
        """Thread: read envelopes from the extension, append to outbox."""
        try:
            while not self._stop.is_set():
                try:
                    msg = read_message(self.stdin)
                except (ValueError, OSError):
                    break
                if msg is None:  # EOF: Chrome closed the port.
                    break
                if not isinstance(msg, dict):
                    continue
                # Extension -> coordinator: record it for run.py.
                self._append_outbox({"direction": "extension_to_coordinator",
                                     "envelope": msg})
                if msg.get("type") == "shutdown":
                    self._stop.set()
                    break
        finally:
            self._stop.set()

    def _send_to_extension(self, obj):
        try:
            write_message(self.stdout, obj)
            return True
        except (BrokenPipeError, OSError):
            # Extension disconnected; the command cannot be delivered.
            return False

    # -- coordinator queue (inbox file) ---------------------------------------

    def _poll_inbox(self):
        try:
            with open(self.inbox, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            return
        new_lines = lines[self._offset:]
        for line in new_lines:
            line = line.strip()
            self._offset += 1
            if not line:
                continue
            try:
                cmd = json.loads(line)
            except ValueError:
                self._append_outbox({"direction": "host_error",
                                     "error": "bad_inbox_json",
                                     "line": line[:200]})
                continue
            self._handle_command(cmd)
        self._write_offset(self._offset)

    def _handle_command(self, cmd):
        if not isinstance(cmd, dict):
            return
        cmd_id = cmd.get("id")
        if cmd.get("auth") != self.secret:
            self._append_outbox({"direction": "host_error",
                                 "error": "bad_auth",
                                 "command_id": cmd_id})
            return
        ctype = cmd.get("type")
        if ctype == "ping":
            # Liveness of the whole chain: forward to the extension so the
            # pong proves the extension is alive too.
            if not self._send_to_extension(
                    {"type": "ping", "nonce": cmd.get("nonce")}):
                self._append_outbox({"direction": "host_error",
                                     "error": "extension_not_connected",
                                     "command_id": cmd_id,
                                     "nonce": cmd.get("nonce")})
            return
        if ctype in ("send", "read_latest", "health", "last_sent", "collect_dom"):
            envelope = dict(cmd)
            envelope.pop("auth", None)
            if not self._send_to_extension(envelope):
                self._append_outbox({"direction": "host_error",
                                     "error": "extension_not_connected",
                                     "command_id": cmd_id,
                                     "nonce": cmd.get("nonce"),
                                     "type": ctype})
            return
        self._append_outbox({"direction": "host_error",
                             "error": "unknown_command_type:" + str(ctype),
                             "command_id": cmd_id})

    # -- main loop ------------------------------------------------------------

    def run(self):
        reader = threading.Thread(target=self._stdin_reader, daemon=True)
        reader.start()
        try:
            while not self._stop.is_set():
                self._write_heartbeat()
                self._poll_inbox()
                # Wait briefly; interrupted promptly by _stop via timeout.
                self._stop.wait(POLL_SECONDS)
        finally:
            self._stop.set()
            reader.join(timeout=2)
        return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Agent Relay native messaging host")
    parser.add_argument("--state-dir", required=True,
                        help="directory holding inbox.jsonl / outbox.jsonl")
    args = parser.parse_args(argv)
    os.makedirs(args.state_dir, exist_ok=True)
    host = NativeHost(args.state_dir)
    return host.run()


if __name__ == "__main__":
    sys.exit(main())
