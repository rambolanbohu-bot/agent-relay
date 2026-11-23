# Agent Relay Skill v1 — 架构方案（ARCHITECTURE-v1.md）

版本：v1.0.0-rc4，2026-11-19。由 Muse 与 ChatGPT 三轮讨论（RELAY-AUTONOMY-POC-01）收敛形成；Leo 已批准；实现方为 Dash（Muse），不是 Codex。

## 1. 项目与目标

- 项目名：Agent Relay Skill v1
- 目标：Muse（网页版会话）与 ChatGPT（真实网页版会话）无障碍沟通，不影响用户其他电脑操作；讨论出结果后发消息给用户，由用户拿主意做决策。
- 模式：Muse 驱动（Muse-driven）。ChatGPT 是独立参与方，负责方案设计与独立审查。
- 成本目标：新增费用 AUD 0（只用已有订阅与额度）。

## 2. 整体架构（四层）

```
ChatGPT（真实网页会话） ⇄ Browser Transport ⇄ Muse Orchestrator ⇄ Persistent State + Evidence
                                                              ↕
                                                    Human Decision Gate → 用户
```

- **Muse Orchestrator（协调器）**：任务状态、消息调度、多轮协作、停止条件、证据记录。由 Muse 会话驱动，每轮一个浏览器任务 + 磁盘状态文件 + handoff 接续；可运行入口是 `orchestrator/run.py`（建项目、推轮次、断点续跑、查状态）。**协调器不是常驻后台程序**——协调器是 Muse 会话本身 + run.py（见 SKILL.md 的实话说明）。**诚实边界：run.py 推进状态不等于能自动唤醒 Muse；handoff 自动唤醒为 NOT YET IMPLEMENTED。**
- **Browser Transport（浏览器传输层）**：真实 Chrome 扩展（`transport/extension/`：DOM 收发、回复写完检测）+ native host（`transport/native_host.py`）+ 调用接口（`transport/adapter.py`）。读用扩展的页面读取，写用 DOM 级填写输入框 + 点击发送；不激活标签页、不把 Chrome 带到前台、不用系统级键盘鼠标。15 秒轮询做实验期检查。Chrome 扩展是嵌进 skill 里的一个通信环节，不是 skill 本身。扩展未在真实 Chrome 加载测试（见 KNOWN-LIMITATIONS.md）。
- **Persistent State + Evidence（持久化状态与证据）**：见第 3 节。
- **Human Decision Gate（人工决策门）**：决策包 + 可信审批通道 + 暂停机制。未获批准绝不执行。执行代码见 `approvals/approvals.py`（令牌仪式 + 状态机 + 执行前检查门）。

## 3. 状态与证据存储

- **v1 运行状态的权威来源：单写入者文件日志**（`orchestrator/file_log.py`，JSONL 追加）。RC2 的文件日志有严格去重（message_id / nonce 唯一）与发送事务（intent → success/failed；核实不了 → UNCERTAIN 并暂停，绝不自动重发）；锁是操作系统锁（`orchestrator/locking.py`），锁文件永不删除。云电脑 SQLite 只有在文件持久化、重启恢复、并发写入三项验证通过后才能成为权威来源；验证未通过之前，SQLite（`orchestrator/schema.sql`）只做只读镜像。
- **GitHub 私有仓库（用户自己的）**：保存经脱敏的设计成果、代码、测试报告和版本快照。明确不做实时队列——GitHub 用于代码、版本化成果和审计，不承载实时消息队列。
- **Windows 本地状态**：仅作缓存和操作日志。
- **证据规则**：每条消息带 message_id、内容 SHA-256、时间戳（以运行日志为准，不以 AI 自述时间为准）、发送方与接收方；接收方重算哈希比对，不一致先按 message_id 重取，仍不一致则标记损坏并停止当轮，绝不在截断内容上继续。

## 4. 文字与文件分离

- 讨论消息里只发文件引用、版本、摘要和哈希，不直接贴文件全文。
- 文件内容校验走用户自己的云电脑、云端硬盘或 GitHub（按引用取回原文再算哈希比对）。

## 5. 人工决策门（GATE-HITL）

- 决策包内容：选项（含推荐项）、证据、成本、风险、建议。
- 审批通道：本地审批页为唯一执行授权通道（安装 PIN + 会话令牌 + 决策绑定的 nonce；执行时重新核对整条批准记录）；Muse 自带审批卡在 RC4 里只是通知/展示通道，不能授权执行（平台收据通道已主动禁用）；决策包哈希加一次性令牌做交叉核对；Windows toast 做提醒（尚未验证的推送）。
- 安全兜底：暂停本身就是保证——超时不等于批准；未批准前不执行；批准只绑定一个决策、一个选项、一个执行规格，偏离规格要重新审批。
- 状态机：pending → approved / rejected / expired。

## 6. v1 五个核心规则

1. 通信不抢焦点。
2. 自主讨论有上限（默认三轮实质讨论，加总时长上限）。
3. 每轮必须有实质内容（Proposal、Objection、Evidence、Resolution 四部分）。
4. 所有消息可追溯（消息 ID、内容哈希、运行日志）。
5. 关键决定必须由人批准。

## 7. 自主讨论状态机

CREATED → DISCUSSING → REVIEWING → CONSENSUS → AWAITING_APPROVAL → APPROVED / REJECTED → COMPLETED。

收敛条件：未解决异议为 0，且双方连续两轮标记“接受”。

## 8. 分工

- Muse（Dash）：协调、讨论、状态管理、云电脑上的文件读写、浏览器收发和监控、skill 文档和验收，以及本包的直接制作。
- ChatGPT：架构设计与独立代码审查，保留独立架构审查权；审核时通过 desktop agent 下载本包到本地。
- Codex：v1 不经过 Codex。如未来需要 Windows 侧工程实现，再由用户决定是否交给 Codex。

## 9. 已验证与待验证

- 已验证：网页双向通信；后台 DOM 写入不抢焦点（GATE-NO-FOCUS-WRITE-01，PASS，当前测试环境）；三轮有内容的联合讨论；Relay 客户端本地 stub 验证 9/9；RC2 的 50 项自动化测试全部通过（file_log 去重与发送事务、locking、approvals 强制检查、relay_client stub、native_host 模拟往返、扩展语法与最小权限、run.py 冒烟）。
- 待验证：断线后自动恢复；真实手机审批通知（批准、拒绝、超时三种结果；Leo 已装好手机端 Muse，测试已开始）；长期无人值守运行；云电脑 SQLite 持久化、重启恢复与并发写入；事件驱动传输；扩展在真实 Chrome 里的加载与往返；install/uninstall 在真实 Windows 上的运行。
- 诚实标注：v1 是 Muse 驱动的自主讨论，不宣称 ChatGPT 已具备自主唤醒能力。Automations 的 E1/E2 并行验证，作为通向真正唤醒的路。
