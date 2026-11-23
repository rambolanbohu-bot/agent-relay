# Transport（传输层）说明

版本：v1.0.0-rc4。

## 两种通道（二选一，默认浏览器方式）

| 通道 | 什么时候用 | 需要用户提供什么 |
|---|---|---|
| **浏览器方式**（默认，见 `browser_adapter.md`） | v1 默认。不需要服务器 | 只需要 Chrome 里登录了 ChatGPT |
| **服务器方式**（可选，`relay_client.py`） | 用户自己有 Relay 服务器时 | 用户自己的 Relay 地址 + 用户自己的 Bearer 令牌 |

两种通道绝不混用。**绝不需要 Leo 的私有 MCP、Leo 的云电脑、Leo 的私有 GitHub 仓库。** 所有环境依赖都由首次安装向导向用户本人收集，存在用户自己的环境里。

## 浏览器方式的组成（RC3：真实代码，不只是文档）

| 组件 | 文件 | 作用 |
|---|---|---|
| Chrome 扩展 | `transport/extension/`（manifest.json、content.js、background.js） | 在 chatgpt.com / muse.ai 标签页里 DOM 读/写、检测回复写完；最小权限（nativeMessaging + tabs，站点只限两站） |
| Native host 启动器 | `transport/agent-relay-host.exe`（源码 `transport/native_host/agent-relay-host.c`） | 真实编译的 Windows .exe：Chrome 拉起它，它再拉起 `native_host.py`，stdin/stdout 原样透传协议。host 清单的 path 永远指向这个 .exe，绝不指向 .bat 或 .py |
| Native host | `transport/native_host.py` | Chrome Native Messaging host：扩展 ↔ 协调器的可运行连接；与 run.py 用本机文件队列（inbox/outbox.jsonl）+ 共享 secret 通信 |
| 调用接口 | `transport/adapter.py` | Muse 侧可调用的接口（health / read_latest / send / poll / verify）；扩展不在线时退回浏览器任务 handoff |
| 适配器说明 | `transport/browser_adapter.md` | 通道说明、健康检查、脆弱性与应对 |

扩展与 native host 的安装见 `docs/INSTALL.md` 第 2b 节与 `transport/extension/README.md`。**诚实范围：扩展只做了语法与结构检查，未在真实 Chrome 加载测试；native host 的往返只在本地模拟过；agent-relay-host.exe 是真实编译的 Windows 程序，但未在真实 Windows 上运行过。**

## relay_client.py（服务器方式客户端，可选）

- 文件：`transport/relay_client.py`（Python 3 标准库，无第三方依赖；从已验证的客户端原样复制，未改动逻辑）。
- 接口（修订版）：`GET /health`、`GET /v1/messages/next?recipient=muse`、`POST /v1/messages/reply`、`GET /v1/messages/{message_id}`。
- 接收字段：discussion_id、message_id、sender=chatgpt、recipient=muse、content、turn_number、source_session。
- 回复字段：sender=muse、recipient=chatgpt、reply_to_message_id、content、run_id。
- 配置只从环境变量读（见 `config.example`）：`AGENT_RELAY_BASE_URL`、`AGENT_RELAY_TOKEN`；可选 `AGENT_RELAY_STATE_FILE`、`AGENT_RELAY_VIA_TAILSCALE=1`。
- 安全规则（写死在实现里）：
  - 只有 sender=chatgpt 的消息才会被当作 ChatGPT 的发言；其他 sender（如 codex）一律拒绝（untrusted_sender，退出码 1），讨论停止。**但这只是客户端核对字段值，不能单独证明来源**——真正的来源保证在服务器端（见 `transport/relay_spec.md`：Relay 按参与方发令牌，服务器强制 sender 与令牌一致）；浏览器方式的来源绑定到页面 origin（扩展从 chatgpt.com 标签页读到的回复就是 sender=chatgpt）。
  - 只传文本，绝不执行、求值或以任何方式运行收到的消息内容。
  - 去重：已回复过的 reply_to_message_id 本地直接拒绝，不再发送。
  - 有限重试：网络错误 / 5xx / 429 最多 3 次，退避 1 秒、2 秒、4 秒；其他 4xx 不重试。
  - 单次调用只做一个操作，客户端内部没有循环；讨论轮次由上层控制（上限 3 轮）。
  - 所有请求 15 秒超时；Token 和代理凭证永不输出到日志。
- 本地验证（2026-11-19，修订版，9 项全部通过，见 tests/TEST-RECORDS-v3.md）：health、next 取 ChatGPT 消息、reply 提交、重复回复被本地拦截、get、sender=codex 被拒绝、空队列、缺 Token 干净报错、500 后重试成功。

## tests/stub_server.py（仅用于本地验证）

- 在 127.0.0.1 上模拟 Relay：要求 Bearer 令牌（测试用 `test-token-123`，仅 stub 用），先返回一条 ChatGPT 测试消息然后返回空，重复回复返回 409；`STUB_FLAKY=1` 时第一次 /health 返回 500。
- 只记录方法、路径、是否带认证、状态码，绝不记录令牌。
- 用法：先启动 stub，再对它跑上面 9 项检查；不要拿它连真实 Relay。

## 配置模板

见 `config.example`。复制一份改成你自己的值（自己的地址、自己的令牌），**绝不要把填好的文件发给任何人，也不要放进安装包里**。
