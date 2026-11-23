# 测试记录（TEST-RECORDS-v5.md）

版本：v1.0.0-rc4-hotfix5。日期：2026-11-20（澳大利亚悉尼时间 AEDT）。本文件只记录已实际验证的内容；未验证的绝不写成已通过，见 `docs/KNOWN-LIMITATIONS.md`。第 1–15 节见 `tests/TEST-RECORDS-v4.md`（保留）；本文件只记 Hotfix5。

时间口径：所有时间以运行日志为准，不以 AI 自述时间为准。

## 16. RC4-hotfix5：ATTEMPT-08 的 BAT 解析缺陷 + B2 仍失败（2026-11-20）

ChatGPT 的 HOTFIX4 静态验收通过（2026-11-20 22:54，ZIP SHA-256 `802babfc…` 一致，91 项，167/167 测试独立复现），但 ATTEMPT-08 部分通过、**未批准发布**：直接安装链通过（install.py、verify_manifest.py、Native Host 驱动退出码均为 0）；ASCII BAT 在真机上解析失败（第 66 行括号、第 85 行 REM %~f，且只修两处仍有控制流异常）；B2 真实发送仍失败（nonce `acfe5a6ddef42ce3`，Adapter 超时/UNCERTAIN，测试文本 `H4-B2-20261120-01` 仍在输入框里）。Leo 于 22:55 授权修复。

修复（见 `docs/CHANGELOG.md` 的 hotfix5 节）：BAT 的 CMD 解析缺陷按整类修（块内消息去 ASCII 括号 + 去 `%~` 展开 + 各失败阶段不同退出码 10–21 + 回归测试 `tests/test_bat_cmd_safety.py`）；B2 发送（`waitForSendButton` 永不解析禁用按钮、`doSend` 填充后立即核实、新错误 `send_button_never_enabled`、只点已启用的按钮）；适配器晚到回执对账（`_wait_outbox` 只数完整行、`send()` 超时后最终扫描、新 `reconcile_send()` + `file_log.send_reconciled()`，晚到回执只有带非空 message_id 才升级为 delivered-late）。**诚实标注：B2 的深层原因（页面为什么没同步输入状态）未从证据证明；send / BAT 修复只在模拟 DOM + 单元测试 + 代码检查里验证过（本机没有真实 Chrome/Windows），真实页面与真实 Windows CMD 解析验证需 ChatGPT 的 ATTEMPT-09 重测；至今没有采集到真实的回复节点 DOM 结构做独立确认。**

### 16.1 诊断证据（ATTEMPT-08，代码级复现）

- **BAT 隐患全貌**：`tests/test_bat_cmd_safety.py` 的扫描器在 Hotfix4 的 ASCII BAT 上检出 **10 处问题**——第 66 行括号、第 85 行 REM `%~f`，外加第 138、154、185、190、203、223、266、279 行的块内消息括号（8 处未被 ChatGPT 单独定位）。这解释了“只修 66 与 85 两处仍有控制流异常”。Hotfix4 的源 BAT 只有 1 处问题（第 85 行 REM `%~f`），且全部失败退出码都是 1（不区分阶段）。
- **B2 失败模式复现**：新的 content.js harness（按钮永不启用 + 禁用的按钮上 click() 为空操作但计入点击数）跑 Hotfix4 的 content.js 时，测试 5l **2 项失败**——返回 `uncertain` + `send_unconfirmed`、点击 1 次（空操作），文本留在输入框里；正好是 ATTEMPT-08 的失败模式。同一 harness 跑 Hotfix5 的 content.js 时 47 项全部通过（5l 报 not_sent + `send_button_never_enabled` + 0 次点击）。
- **适配器竞态**：`_wait_outbox` 在无 FileLock 的情况下读 outbox，把看过的每一行都算“已读”——写了一半时读到的回执永远丢失。测试 `test_partial_line_is_not_counted_as_seen` 证明：写了一半的行（无尾随换行）不被匹配，写完后能找到。

### 16.2 测试结果（2026-11-20，Dash 本地）

batch 1：28 项（原 23 项 + file_log send_reconciled 5 项），0 失败，SUITE: PASS（5.5 秒）；batch 2：56 项，0 失败，SUITE: PASS（12.8 秒）；batch 3：105 项（原 88 项 + bat_cmd_safety 6 项 + adapter_late_receipt 11 项），0 失败，SUITE: PASS（99.0 秒）；全量：189 项，0 失败，0 错误，0 跳过，SUITE: PASS（117.4 秒）。原始输出见 `tests/test-output-rc4-batch-{1,2,3}.txt` / `tests/test-output-rc4.txt`。另做：`py_compile` 全部 Python 文件通过；`manifest.json` 合法 JSON；content.js 与 background.js 通过 `node --check`；密钥扫描干净（只有 localhost stub / 测试里的 test-token-123；包内无 Leo 的密码、Cookie、会话令牌或个人聊天内容）；ZIP 里无 `__pycache__` / `.pyc`；发布门在好包上通过、在故意去掉 .exe 的坏包上拒绝（非零退出、无 .sha256、无 ZIP，预先放好的旧 ZIP/.sha256 也被删掉）。

发布门结果：ZIP `agent-relay-skill-v1.0.0-rc4-hotfix5.zip`（见随包的 `.sha256` 文件，内含 SHA-256）；MANIFEST.json 75 个文件；.exe 224,515 字节，SHA-256 `0e6a9748685d48e435a7f07775bdb9ba020f1348661a154b9276e3bc37bf36de`，与清单一致；清单在包目录与 ZIP 里逐字节一致；check_package 对包目录与 ZIP 都通过。

### 16.3 全量原始输出（`tests/test-output-rc4.txt`，末尾汇总）

```
Ran 189 tests in 117.443s
OK
Tests run: 189, failures: 0, errors: 0, skipped: 0
SUITE: PASS
```
