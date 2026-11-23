# Agent Relay Skill v1.0.0-rc4 — 包说明

## 这是什么

Agent Relay Skill：让 Muse 和 ChatGPT 两个 AI 自己讨论问题，讨论出结果后告诉你，由你拿主意。整个过程不抢你的屏幕、键盘和鼠标。

- 版本：v1.0.0-rc4（候选版）
- 日期：2026-11-19
- 成本目标：新增费用 AUD 0
- 实现方：Dash（Muse）直接制作；ChatGPT 独立审核；不经过 Codex（按 Leo 的决定）。

## 包里有什么

```
agent-relay-skill/
  SKILL.md            # 给用户和 Muse 的主文件：三步用法、五句命令、首次安装向导
  orchestrator/       # 协调器：run.py 可运行入口（两种模式）、运行手册、SQLite schema、文件日志、跨平台锁、看门狗
  transport/          # 传输层：Chrome 扩展（真实代码）+ native host .exe 启动器 + native host + 调用接口 + Relay 客户端（可选）+ 本地 stub + Relay 规范
  protocol/           # 讨论协议：消息格式、轮次规则、可靠性与恢复
  approvals/          # 人工决策门：决策包、令牌仪式、通道发出凭证、执行时检查 + 可执行模块 approvals.py + 本地审批页 local_approval_page.py
  tests/              # 测试记录 + 自动化套件（run_tests.py，88 项）+ 三道验收门验收脚本
  docs/               # 本文件、架构、验收门、安装说明、已知限制、变更记录
  install.bat         # Windows 安装启动器（调用 install.py；RC3 已修延迟展开 bug）
  install.py          # Windows 安装器：先检查、自动生成 host 清单与注册表、生成安装 PIN、写安装清单、失败回滚
  uninstall.bat       # Windows 卸载启动器（调用 uninstall.py；RC3 已修延迟展开 bug）
  uninstall.py        # Windows 卸载器：只清理安装清单里的资源，注册表项只在仍指向本次安装时才删
```

## 先看这三份

1. **`SKILL.md`** —— 用户怎么用（三步 + 五句话），以及 Muse 执行时的规则。
2. **`docs/INSTALL.md`** —— 安装、启动、停止、继续、卸载，首次安装向导的每一步。
3. **`docs/KNOWN-LIMITATIONS.md`** —— 没验证过的东西都在这里，一个不少。

## 三道验收门状态（诚实版）

| 门 | 状态 |
|---|---|
| GATE-NO-FOCUS（不抢前台、键盘、鼠标） | **PASS（当前测试环境）**——两次后台写入实测通过 |
| GATE-AUTONOMY（无人值守连续讨论） | **部分验证**——三轮讨论由 Muse 驱动完成；ChatGPT 自发起、长期无人值守、自动恢复尚未验证；**handoff 自动唤醒为 NOT YET IMPLEMENTED**（run.py 推进状态不证明能自动唤醒 Muse） |
| GATE-HITL（关键决策通知与审批） | **PENDING（未验证）**——审批重做为通道发出凭证（approvals.py + 本地审批页）；Leo 已装好手机端 Muse，手机推送测试已开始：Test 1（批准）已通过，Test 2（拒绝）与 Test 3（超时）待验证 |

## 安装

解压 ZIP → 在 Muse 里说“安装 Agent Relay” → 跟向导走完。详见 `docs/INSTALL.md`。

## 绝不包含的东西

这个安装包里**没有任何人**的密码、登录状态（cookie）、令牌、浏览器用户数据、Relay 地址、私有仓库地址。所有环境依赖都由首次安装向导向用户本人收集，存在用户自己的环境里。
