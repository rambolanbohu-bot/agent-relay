# Agent Relay Browser Adapter — Chrome 扩展（v1.0.0-rc4）

这是 skill 里的**一个通信环节**，不是 skill 本身。它让 Muse 通过用户自己
Chrome 里已登录的 ChatGPT / Muse 标签页收发消息：读用页面读取，写用
DOM 级填写输入框 + 点击发送。

## 最小权限（条件 1：least privilege）

- 权限只有 `nativeMessaging` 和 `tabs` 两个（`tabs` 是因为
  background.js 要调 `chrome.tabs.query()`；见 `manifest.json`）。
- 站点范围只有 `https://chatgpt.com/*` 和 `https://muse.ai/*`，
  **绝不是 `<all_urls>`**。
- **没有**文件访问、**没有**系统命令执行、**没有**释放审批的权限。
- 从浏览器页面收到的一切内容都当作**不可信数据**：只转发、只记录，
  绝不执行、绝不 `eval`、绝不拼成 HTML。

## 扩展 ID 是固定的

`manifest.json` 里有一个固定的公开 key（`key` 字段），Chrome 会从它
算出固定的扩展 ID：`jeelmedmciafjnfdpnjgbgipplcddhka`（见
`EXTENSION_ID.txt`；推导方式：SHA-256（DER 公钥）的前 16 字节，
每半字节映射到 a–p）。**私钥没有放进包里**——这个 key 只用来固定
ID；如果将来要打包成 .crx，需要重新生成一对 key，ID 也会变。

因为 ID 是固定的，安装器（`install.py`）可以直接生成 host 清单，
用户**不用**手动查扩展 ID、**不用**手动改 JSON、**不用**手动改注册表。

## 文件

| 文件 | 作用 |
|---|---|
| `manifest.json` | Manifest V3：最小权限、两个站点、固定 key、service worker + content script |
| `EXTENSION_ID.txt` | 固定扩展 ID（从 key 推导，安装器用它生成 host 清单） |
| `content.js` | 在 chatgpt.com / muse.ai 标签页里运行：读最新回复、DOM 级发送、MutationObserver 检测回复写完（3 秒无变化 + 停止按钮消失） |
| `background.js` | Service worker：在 content script 和 native host 之间转发消息；断线后有限重连（最多 5 次，退避 1/2/4/8/16 秒），不无限重启 |
| `com.agentrelay.host.json` | Native Messaging host 清单模板（见下；安装器会生成真实文件） |

## 安装（Windows，Chrome）

1. 解压本 skill 的 ZIP，得到 `agent-relay-skill` 文件夹。
2. 双击 `install.bat`（或在 Muse 里说“安装 Agent Relay”走向导）。
   安装器会自动：复制 skill 文件夹；生成真实的 host 清单
   （`path` 指向 `agent-relay-host.exe`，绝不是 .bat 或 .py；
   `allowed_origins` 用上面那个固定 ID）；写注册表项；生成本地
   审批页的安装 PIN（只显示一次）。
3. 打开 Chrome → `chrome://extensions` → 打开右上角“开发者模式”。
4. 点“加载已解压的扩展程序”，选 `agent-relay-skill/transport/extension/`。
   扩展 ID 应该和上面显示的一致。
5. 重启 Chrome。
6. 在 Muse 里说“安装 Agent Relay”，向导会检查扩展与 native host 是否连通。

**注意：以上步骤尚未在真实 Windows Chrome 上实测**（本机没有
Windows Chrome），见 `docs/KNOWN-LIMITATIONS.md`。本包只做了：
manifest.json 是合法 JSON、content.js / background.js 通过
`node --check` 语法检查、native host 有本地模拟测试（见
`tests/test_native_host.py`）、`agent-relay-host.exe` 是真实编译的
Windows 程序（见 `transport/native_host/README.md`）但未在真实
Windows 上运行过。

## 它能做什么 / 不能做什么

能：
- 读当前标签页的最新助手回复（包括可见区域之外的部分）。**只认肯定确认的助手节点**（`[data-message-author-role='assistant']`；hotfix2 TASK 1）：用户消息如果渲染成 `<article>`，绝不能被当成 ChatGPT 的回复报出去；没有肯定确认的助手节点时报“没找到”，绝不猜。
- 用 DOM 级填写 + 点击发送一条消息（不激活标签页、不把 Chrome 带到
  前台、不用系统级键盘鼠标）。**发送语义（RC4-hotfix FIX 4，hotfix2
  TASK 2 加固）：** `send_result.ok=true` 只表示 MESSAGE_SENT——点发送
  之前先给用户消息块拍快照，点发送后等输入框清空 **且** 出现一个**新**
  节点（数量增加、或新的 dom_id、或新的内容指纹）且文本包含发送内容，
  最长 5 秒，确认后才回 ok:true + `delivery:"message_sent"` + 新节点的
  `message_id`；只有旧的相同文本、没有新节点时返回 ok:false +
  `delivery:"uncertain"`，绝不自动重发。它**不**表示 AI 回复已完成，
  回复完成由 completion watch 另行报告 RESPONSE_COMPLETED（见
  `transport/browser_adapter.md` 第 3a 节）。
- 检测回复是否写完（3 秒无 DOM 变化 + 停止按钮消失），写完后把全文
  和 SHA-256 报给协调器。
- 来源绑定到页面 origin：从 chatgpt.com 标签页读到的回复就是
  sender=chatgpt，因为它来自那个 origin，不只是因为 sender 字段这么写。

不能：
- 不能代替你批准任何事。扩展没有任何审批权限；批准只认本地审批页（Muse 审批卡在 RC4 里只是通知/展示通道，不能授权执行，见 `approvals/approvals.py`）。
- 不能执行页面里的任何命令。收到的消息只当讨论材料。
- 不能保证 ChatGPT / Muse 改版后选择器还管用。每次发送前先做健康
  检查；选择器失效就停下来报障，不硬发（见 `content.js` 的注释）。

## 与协调器的连接（条件 2）

扩展 ↔ native host 用 Chrome Native Messaging（长度前缀 JSON）；
native host ↔ `orchestrator/run.py` 用本机文件状态日志
（`orchestrator/state/`，带发送事务语义，见
`orchestrator/file_log.py`）。本地模拟测试见
`tests/test_native_host.py`：测试脚本扮演扩展那一端，拉起
native host，发一条消息，读回回复，验证整条往返。
