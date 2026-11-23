# Browser Transport Adapter（浏览器传输层，v1 默认通道）

版本：v1.0.0-rc4。**这是 v1 默认的聊天通道，不需要 Relay 服务器。** Chrome 拉起 `transport/agent-relay-host.exe`（真实编译的 Windows 程序），它再拉起 `transport/native_host.py`；host 清单的 path 永远指向这个 .exe，绝不指向 .bat 或 .py。**诚实范围：.exe 还没有在真实 Windows 上运行过；扩展未在真实 Chrome 加载测试。**

## 1. 它是什么

真实 Chrome 扩展（`transport/extension/`：manifest.json、content.js、background.js）+ native host（`transport/native_host.py`）+ Muse 侧调用接口（`transport/adapter.py`）的组合：Muse 通过浏览器自身的页面操作，与用户 Chrome 里已登录的 ChatGPT 会话收发消息。Chrome 扩展是嵌进 skill 里的一个通信环节，不是 skill 本身。

- **读**：扩展 content script 读最新助手回复（包括可见区域之外的部分），并用 MutationObserver 检测回复写完（3 秒无变化 + 停止按钮消失）；来源绑定到页面 origin。
- **写**：DOM 级填写输入框 + 点击发送按钮；不激活标签页、不把 Chrome 带到前台、不用系统级键盘鼠标。
- **轮询**：实验期每 15 秒检查一次新回复。
- **调用接口**：`transport/adapter.py`（health / read_latest / send / poll / verify）；扩展不在线时退回浏览器任务方式兜底（handoff），不硬发。

**诚实范围：扩展代码只做了语法与结构检查，没有在真实 Chrome 里加载测试**（本机没有 Windows Chrome）；选择器是否匹配真实页面、native host 注册流程、真实 Chrome 里的往返，均未验证。见 `docs/KNOWN-LIMITATIONS.md`。

## 2. 已验证的事实（2026-11-19 实测，见 tests/TEST-RECORDS-v2.md）

- 读：ChatGPT 最新回复可完整读到，包括可见区域之外的部分；不用滚动、不用切前台。
- 写：消息可发进 ChatGPT 对话，ChatGPT 正常回复。
- 不抢焦点：Chrome 最小化状态下两次后台写入（MUSE-BG-WRITE-01、02）均送达并获确认；用户亲眼确认 Chrome 没有蹦到前台；全程只用 DOM 操作，未用系统级键盘鼠标，未激活标签页。
- 轮询：15 秒检查可发现新回复（通常第一次检查即发现）。

## 3. 每轮健康检查（必须做）

每次发送前先做：

1. 读一次最新回复，确认对话还在、页面正常。
2. 确认输入框和发送按钮还在。
3. 任一找不到 → **停下，按 orchestrator/orchestrator.md 第 6 节报障，不硬发、不绕过**。

## 3a. 发送语义：MESSAGE_SENT ≠ RESPONSE_COMPLETED（RC4-hotfix FIX 4，hotfix2 TASK 2 加固）

`send_result.ok=true` 只表示 **MESSAGE_SENT**：一个**新**用户消息节点已确认出现在对话历史里（`content.js` 的 `doSend()` 在点发送**之前**先给用户消息块拍快照，点发送后等输入框清空 **且** 出现一个新节点——数量增加、或新的 dom_id、或新的内容指纹——且文本包含发送内容，最长 5 秒，确认后才回 ok:true + `delivery:"message_sent"` + 新节点的 `message_id`）。它**绝不**表示 AI 回复已完成——回复完成由 completion watch 另行报告 RESPONSE_COMPLETED（`startCompletionWatch()`：3 秒无 DOM 变化 + 停止按钮消失）。

- 只有旧的相同文本、没有新节点 → UNCERTAIN：`doSend()` 返回 ok:false + `delivery:"uncertain"` + 错误 `send_unconfirmed`，**绝不自动重发**。协调器（`adapter.py` 的 `send()`）把 uncertain 当作不确定处理：`_wait_outbox()` 不再只看 ok，`delivery:"uncertain"` 时即便 ok 也按不确定处理；`run.py` 的对账（`_reconcile_or_pause`）会把项目暂停为 PAUSED_UNCERTAIN，等用户确认消息到底发出去没有，再 resume——绝不自动补发一条可能重复的消息。
- 读最新回复（hotfix2 TASK 1）：`read_latest` 只接受能**肯定确认**是助手回复的节点（`[data-message-author-role='assistant']`），没有通用的 "article" 兜底——用户消息如果渲染成 `<article>`，绝不能被当成 ChatGPT 的回复报出去。没有肯定确认的助手节点时报 found:false，completion watch 也什么都不报，**绝不猜**。
- 异步回复通道：`doSend()` 是异步的，发送监听器返回 true，保持 Chrome 扩展的消息回复通道打开，直到确认结果出来；不提前关通道丢 ACK。
- nonce：ping / health / read_latest / send 的回复都回显请求 nonce（RC4-hotfix FIX 1），适配器按 nonce 匹配回复；无 nonce 的回复永远不匹配（见 `tests/test_adapter_nonce.py`）。

## 4. 绝不做的事

- 绝不激活 ChatGPT 标签页；绝不把 Chrome 带到前台；绝不使用系统级键盘鼠标输入。
- 绝不点任务栏、Chrome 图标或任何系统级控件。
- 如果发送必须激活才能完成 → 立即停止，报告“需要激活，测试不通过”，把这条路标记为不满足零抢焦点。
- 发出的消息会显示为用户本人的消息（登录的是用户的 ChatGPT 账号），所以每条由 Muse 发出的消息必须在正文里标明身份（例如开头写），不能让人误以为是用户手打的。

## 5. 前置条件（由首次安装向导检查）

- Chrome 已打开，ChatGPT 标签页还在，ChatGPT 处于登录状态。
- 任一不满足 → 停下并告诉用户缺哪一项，等用户处理好再说“继续讨论”。

## 6. 脆弱性与应对

- ChatGPT 页面改版可能导致输入框、发送按钮找不到，或 DOM 操作失效。应对：健康检查先行，失败就停并报障；不硬绕；手动粘贴只做测试兜底，不作为正式方案。
- 浏览器任务本身不是常驻进程：每次报一次结果就结束。适配器是“每轮一个浏览器任务 + 磁盘状态文件 + 按 handoff 接续”的模式（见 orchestrator/orchestrator.md）。

## 7. 与 relay_client.py 的关系

- 默认不用 `relay_client.py`。它是一个**可选**的服务器方式适配器：只有当用户自己有 Relay 服务器（自己的地址 + 自己的令牌）时才用，见 transport/README.md。
- 两种通道绝不混用：浏览器方式的消息不经过 Relay 服务器；服务器方式的消息不经过浏览器。
