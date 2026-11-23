#!/usr/bin/env python3
"""Agent Relay Skill v1 — 看门狗（watchdog）：只检查，不重启、不发消息。

做法：
- 每轮讨论由协调器写一个带时间戳的心跳文件 state/heartbeat.json：
      {"project_id": "...", "last_update": "<UTC ISO 时间>",
       "turn_number": 3, "status": "DISCUSSING"}
- 看门狗定时读心跳文件（默认每 5 分钟检查一次，只在有活跃讨论时运行）：
  活跃讨论中超过 --stale-seconds（默认 600 秒）没更新 → 判定为停滞。

看门狗只做一件事：报告状态。恢复由 Muse 会话做（按
orchestrator/orchestrator.md 第 5 节），看门狗本身不推理、不生成讨论
内容、不向 ChatGPT 发消息、不重启任何程序。

退出码：0 正常（ok），1 停滞（stale），2 心跳文件缺失或损坏（missing/error）。
输出：单行 JSON，含 status、age_seconds、project_id、last_update。

用法：
    python3 watchdog.py --heartbeat state/heartbeat.json
    python3 watchdog.py --heartbeat state/heartbeat.json --stale-seconds 600

定时检查示例（Muse 侧定时任务，每 5 分钟一次，只在有活跃讨论时运行）：
  若退出码为 1 或 2，唤醒一次 Muse 会话并向用户报告停滞；同一项目连续
  两次恢复失败 → 转为 BLOCKED，通知用户，等用户决定。
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def parse_time(value):
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def check(heartbeat_path, stale_seconds, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        with open(heartbeat_path, "r", encoding="utf-8") as f:
            beat = json.load(f)
    except FileNotFoundError:
        return {"status": "missing", "age_seconds": None,
                "project_id": None, "last_update": None,
                "detail": "heartbeat file not found"}, 2
    except (ValueError, OSError) as e:
        return {"status": "error", "age_seconds": None,
                "project_id": None, "last_update": None,
                "detail": f"cannot read heartbeat file: {e}"}, 2
    last = parse_time(beat.get("last_update"))
    if last is None:
        return {"status": "error", "age_seconds": None,
                "project_id": beat.get("project_id"),
                "last_update": beat.get("last_update"),
                "detail": "heartbeat has no valid last_update"}, 2
    age = (now - last).total_seconds()
    if age < 0:
        age = 0
    status = "stale" if age > stale_seconds else "ok"
    return {"status": status, "age_seconds": round(age, 1),
            "project_id": beat.get("project_id"),
            "last_update": beat.get("last_update"),
            "turn_number": beat.get("turn_number"),
            "stale_threshold_seconds": stale_seconds}, (1 if status == "stale" else 0)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Agent Relay watchdog")
    parser.add_argument("--heartbeat", required=True,
                        help="path to state/heartbeat.json")
    parser.add_argument("--stale-seconds", type=int, default=600,
                        help="stale threshold in seconds (default 600)")
    args = parser.parse_args(argv)
    result, code = check(args.heartbeat, args.stale_seconds)
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
