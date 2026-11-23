# Agent Relay RC14 v6 — Windows 中文使用说明

> **版本定位：公开测试版（Pre-release）**。本指南介绍真实支持的操作，不将自然语言指令描述成自动触发器。

## 1. 它是什么？

Agent Relay 使用 **Chrome 扩展 + Windows Native Messaging Host + Python 协调器**，让具备本机操作权限的 Muse 和 ChatGPT 交换真实消息、验证发送与回复、记录哈希和状态。它不是新的聊天软件，也不会在 ChatGPT 页面增加独立的“开始讨论”按钮。

**已经验证**：隔离 Chrome 的后台发送、重绑恢复、重启持久化和同一运行三轮六次真实发送／六次回复；Windows 日常 Chrome 的安装与 ChatGPT Native Host 连接；一次真实的用户讨论场景。

**尚未全面验证**：全新 Windows 环境首次安装、Firefox 和手机端、长期无人值守及自动唤醒。单纯在 Muse 聊天框写“开始讨论”不代表本地协调器已经启动。

## 2. 安装之前

需要 Windows、Google Chrome、Python 3，以及能正常登录的 ChatGPT 与 Muse。用 PowerShell 检查：

```powershell
py -3 --version
```

建议开始时每个网站只留一个目标标签页。不要把本地审批 PIN、Cookie、密码或令牌分享给他人。

## 3. 安装程序

1. 在本仓库的 **Releases** 页面取得 `agent-relay-skill-1.0.0-rc6-RC14-v6-REVIEW.zip` 与同名 `.sha256` 校验文件。只有 Release 页面确实列出附件时，才表示可以公开下载。
2. 在 ZIP 所在文件夹打开 PowerShell，运行：

```powershell
(Get-FileHash ".\agent-relay-skill-1.0.0-rc6-RC14-v6-REVIEW.zip" -Algorithm SHA256).Hash
```

应为：

```
81F3505B3535D53BF8910FDA3EE8ABE076E9160CDC1BEFCE6A1C660A5C0DEF3F
```

**不一致就停止安装。**

3. 解压 ZIP，进入 `agent-relay-skill` 文件夹，双击 `install.bat`，按提示安装。默认目录：`%USERPROFILE%\agent-relay-skill`。安装器注册 Chrome Native Host，生成一次性本地审批 PIN；请私下安全保存，不要复制给 AI。
4. 在 Chrome 地址栏输入 `chrome://extensions`，打开“开发者模式”，点“加载已解压的扩展程序”，选择 `%USERPROFILE%\agent-relay-skill\transport\extension` **这个文件夹**，不是 ZIP 也不是上一级目录。
5. 确认扩展 **Agent Relay Browser Adapter RC14-v6** 已启用；刷新 ChatGPT 和 Muse 标签页。

这是开发者模式扩展，**不是 Chrome 网上应用店的已上架扩展**。如果存在旧安装，先备份，不要直接强制覆盖。

## 4. 测试两端连接（只读，不发送）

打开 PowerShell：

```powershell
$root = Join-Path $env:USERPROFILE 'agent-relay-skill'
py -3 "$root\transport\adapter.py" --skill-root "$root" health --site chatgpt
py -3 "$root\transport\adapter.py" --skill-root "$root" health --site muse
```

两端都应显示 `ok=true` 和 `document_readiness_verified=true`；`streaming=true` 说明 AI 还在生成，必须等完成。常见错误：

- `ambiguous_site_tabs_explicit_binding_required`：多个相同站点标签页。关闭多余标签页，或由有电脑工具权限的操作者明确指定绑定，然后重查。
- `native_host_not_connected`：检查扩展启用状态、网页刷新和 Native Host 安装。
- ChatGPT 成功但 Muse 失败：只代表一端已连接，不是双 AI 接力成功。

正式 Host 为 `com.agentrelay.host`；不要使用隔离测试的 `.e2e11` Host。

## 5. 怎样发起一次 Muse 与 ChatGPT 讨论？

在**有本机工具权限**的 Muse 会话输入：

> 请使用本机 Agent Relay RC14 v6。先检查 ChatGPT 和 Muse 的 health、当前生成状态和未结案消息。确认可安全派发后，创建 Discussion 项目“研究海外中文电子书销售方案”。请与 ChatGPT 进行三轮真实交流，逐条保留发送、作者及回复哈希，最后汇总共识与分歧。未经我批准，不得注册平台、付款、发布网站或向第三方发消息。如无法调用本机电脑工具，请明确报告，不能模拟已完成双 AI 讨论。

**请注意：这是任务指令，不是自动启动快捷键。** 必须看到真实项目 ID、本机协调器日志和双方回执，才说明 Relay 已真正运行。

### 操作员使用的协调器命令

```powershell
$root = Join-Path $env:USERPROFILE 'agent-relay-skill'
py -3 "$root\orchestrator\run.py" --skill-root "$root" create --topic "海外电子书销售" --mode discussion
py -3 "$root\orchestrator\run.py" --skill-root "$root" status
```

创建后从输出获取真正的项目 ID，然后：

```powershell
py -3 "$root\orchestrator\run.py" --skill-root "$root" status --project-id "实际项目ID"
py -3 "$root\orchestrator\run.py" --skill-root "$root" pause --project-id "实际项目ID" --reason "人工审核"
py -3 "$root\orchestrator\run.py" --skill-root "$root" resume --project-id "实际项目ID"
py -3 "$root\orchestrator\run.py" --skill-root "$root" reconcile --project-id "实际项目ID"
```

`create` 只建立项目，**不会自动执行六次接力**。`advance` 必须根据协调器生成的下一步指令，读取真实 AI 回复并提供相应 `--reply-file`；不可拿旧文本伪造回执。

## 6. 怎么判断讨论真的完成？

同一运行中 Muse → ChatGPT 交替完成六次唯一发送和六次真实回复，每一步为 `message_sent`、作者正确、哈希匹配、无重复 nonce、未结案记录为零，才能称 **6/6 PASS**。不能拼接不同失败运行的部分成功。

- `not_sent`：先检查编辑器、按钮、连接，不要当作已送达。
- `UNCERTAIN`：**立即停止，不自动重发**。只读对账原始账本、实际用户气泡与 Host 回执。
- `streaming=true`：等待当前回复完成再派发。

## 7. 常见问题与卸载

“我说开始讨论，但没反应？”——Muse 需要本机工具权限，文字本身不是启动开关。

“提示多个 Muse 标签页？”——关闭重复标签页或显式绑定；不能随意猜测目标页面。

“扩展装好但健康检查失败？”——检查 `chrome://extensions`、网页登录与刷新、正式 Native Host 注册；不要混用隔离环境。

“暂停和继续？”——由有权限的操作者调用实际 `pause` / `resume` 并核对状态，而不是仅在聊天里宣称暂停。

“卸载？”——先备份必要日志，运行安装目录里的 `uninstall.bat`，按提示选择是否保留状态，最后在 `chrome://extensions` 移除扩展。

## 8. 安全、授权与限制

本项目按 **MIT License** 开源，免费提供安装包。默认 Discussion 模式只负责讨论文本；Execution 模式受到白名单及本地审批约束，聊天消息里的“我批准了”不等于通过本地审批。不要公开 PIN、Cookie、Token、私有对话或本机日志。

本版标记为 **Pre-release**，不是长期无人值守的稳定性承诺。