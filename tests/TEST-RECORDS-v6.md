# 测试记录（TEST-RECORDS-v6.md）

版本：v1.0.0-rc4-hotfix6。日期：2026-11-21（澳大利亚悉尼时间 AEDT）。本文件只记录已实际验证的内容；未验证的绝不写成已通过，见 `docs/KNOWN-LIMITATIONS.md`。第 1–16 节见 `tests/TEST-RECORDS-v4.md`（第 1–15 节）与 `tests/TEST-RECORDS-v5.md`（第 16 节，Hotfix5）；本文件只记 Hotfix6。

时间口径：所有时间以运行日志为准，不以 AI 自述时间为准。

## 17. RC4-hotfix6：ATTEMPT-09 的 BAT 控制流 + B2/B3 误判 + B4 最小化发送（2026-11-21）

ChatGPT 的 HOTFIX5 独立审计（2026-11-21 00:23，文件 `AGENT_RELAY_HOTFIX5_ATTEMPT09_AUDIT.md`）判 PARTIAL PASS / RELEASE BLOCKED：输入完整性通过（ZIP `0c9132f4…`、ASCII BAT `19d1e586…`、包内 BAT `ce8a45a0…` 均一致，94 项，check_package PASS），静态 BAT 安全 6/6 PASS、batch 1 28/28 PASS、adapter 晚到回执 11/11 PASS；**batch 2 超时 + test_content_js.py 没在时限内跑完——不得据此标 PASS**。直接安装链通过（install.py、verify_manifest.py、驱动均退出码 0；扩展 ID 正确且已启用；health ok=true，tab ID `1527581903`）。四处失败：BAT 自动段 FAIL（再现——日志只有 init 就跳到 Cleanup，exit 2，安装没跑）；B2 FAIL（假阴性——消息 `H5-B2-20261120-01` 与回复 `ACK-H5-B2-20261120-01` 都在真页面上，Adapter 却报 send_unconfirmed/uncertain，nonce `bf6c31daea2fa05b`）；B3 FAIL（read_latest 返回 found=false，尽管 ACK 可见，nonce `1d46c42f31770568`）；B4 FAIL（最小化后台发送报 send_button_missing_after_input / not_sent，nonce `e6d1c25e383db40d`）。Leo 于 00:24 授权修复。ROUND 25 回复（00:39，思考 11 分 11 秒）补充：真实 DOM 结构没拿到；两个 role 选择器仍是未验证的假设；ChatGPT 给了一段脱敏 DOM 采集代码；B4 输入框实际接受了输入、恢复后前台按钮可见，最小化时按钮是否渲染仍未证明。

修复（见 `docs/CHANGELOG.md` 的 hotfix6 节）：P1——整块 BAT 废弃，阶段逻辑搬进 Python（`windows_e2e_test/e2e_runner.py` 阶段状态机 + 45 行薄 BAT 入口，ASCII 副本与包内 BAT 字节相同）；B2/B3——多策略识别（备用 role 属性选择器、回合容器、文本锚、回合后继兜底）+ 识别失败时附脱敏诊断盘点 + 回声防护，证据标准未降低；新增只读脱敏 DOM 采集器（content.js `doCollectDom` + adapter.py `collect_dom`，ROUND 25 的代码移植）；B4——最小化按钮时间序列日志（before_input / after_input / during_wait / timeout 或 button_found + visibilityState），隐藏标签页按钮等待上限 10 秒。**诚实标注：识别 / 发送 / BAT 修复只在模拟 DOM + 单元测试里验证过（本机没有真实 Chrome/Windows），真实页面验证需 ChatGPT 的 ATTEMPT-10 重测；至今没有采集到真实的回复节点 DOM 结构——ROUND 25 的采集器是 ATTEMPT-10 采集它的工具，不是数据本身。**

### 17.1 诊断证据（ATTEMPT-09，代码级复现）

- **BAT 控制流**：Hotfix5 的 ASCII BAT 在真机上从 init 直接跳到 Cleanup（exit 2），安装没跑、安装目录不存在、测试注册表项不存在、无 A 段驱动 JSON。`tests/test_bat_cmd_safety.py` 只覆盖消息行 + 括号深度，拦不住这种控制流故障。新测试 `tests/test_e2e_runner.py`（16 项）直接覆盖该故障模式：安装失败 → exit 14 且卸载**绝不**被调（标记只有 INIT/PREFLIGHT/INSTALL/CLEANUP）；驱动失败 → exit 22 且 B 段绝不跑；安装从未完成时即使测试键莫名存在也不调卸载。
- **B2/B3 假阴性**：新 harness（37 项新增检查）跑 Hotfix5 的 content.js 时 14 项新检查失败——备用 role 属性（6a×2、6b×2）、ATTEMPT-09 精确场景（6c×2）、隐藏标签页按钮（6d×3、6e×4）、诊断盘点（6f 首项）。同一 harness 跑 Hotfix6 的 content.js 时 84 项全部通过。
- **B4 最小化按钮**：ROUND 25 证明输入框实际接受了输入、恢复后按钮可见——“按钮从未渲染”未证明。Hotfix6 不猜测原因，改为记录时间序列：6d（隐藏标签页、按钮 6 秒后出现 → message_sent + 四点时间序列）与 6e（按钮永不出现 → not_sent + 以 button.exists=false 的 "timeout" 收尾）。

### 17.2 测试结果（2026-11-21，Dash 本地）

batch 1：28 项，0 失败，SUITE: PASS（5.6 秒）；batch 2：56 项，0 失败，SUITE: PASS（12.8 秒）；batch 3：135 项（原 105 项 + e2e_runner 16 项 + adapter_collect_dom 9 项 + bat_cmd_safety 由 6 项增至 10 项 + content_js harness 由 47 项增至 84 项，计入 test_content_js 的 1 项），0 失败，SUITE: PASS（131.4 秒）；全量：219 项，0 失败，0 错误，0 跳过，SUITE: PASS（149.5 秒）。原始输出见 `tests/test-output-rc4-batch-{1,2,3}.txt` / `tests/test-output-rc4.txt`。另做：`py_compile` 全部 Python 文件通过；`manifest.json` 合法 JSON；content.js 与 background.js 通过 `node --check`；密钥扫描干净（包内无 Leo 的密码、Cookie、会话令牌或个人聊天内容）；ZIP 里无 `__pycache__` / `.pyc`；发布门在好包上通过、在故意去掉 .exe 的坏包上拒绝（非零退出、无 .sha256、无 ZIP，预先放好的旧 ZIP/.sha256 也被删掉）。

发布门结果：ZIP `agent-relay-skill-v1.0.0-rc4-hotfix6.zip`（见随包的 `.sha256` 文件，内含 SHA-256）；MANIFEST.json 79 个文件；.exe 224,515 字节，SHA-256 `0e6a9748685d48e435a7f07775bdb9ba020f1348661a154b9276e3bc37bf36de`，与清单一致；清单在包目录与 ZIP 里逐字节一致；check_package 对包目录与 ZIP 都通过。

### 17.3 构建中发现并修好的 harness 缺陷（process.exit 截断）

全量第一次跑时 batch 3 失败 3 项：2 项是 `test_check_package`（MANIFEST.json 在构建中途被改过文件后变旧——构建流程的正常中间态，见下），1 项是 `test_content_js`。后者根因：Hotfix6 的 harness 输出约 71 KB（每项检查的 detail 都是完整结果 JSON，含 button_timeline），而 harness 末尾在 `console.log` 后立即调 `process.exit()`——stdout 是管道时（Python 测试用 `subprocess.run(capture_output=True)` 捕获），console.log 的写入是异步的，`process.exit()` 会截断还没排空的部分；实测只收到前 65,536 字节（正好一个管道缓冲区），JSON 解析失败。Hotfix5 的输出约 15 KB，不到一个缓冲区，所以这场竞态从未出现；用 shell 重定向到文件时写入是同步的，所以直接跑 harness 看不出问题。修法：改设 `process.exitCode`，让事件循环排空 stdout 后再自然退出，退出码不变；经 subprocess 捕获复测：stdout 71,043 字节完整、JSON 正常解析、84 项全过、returncode 0。另：MANIFEST.json 的两次变旧都是构建流程的正常中间态——第一次是复制 Hotfix5 树后改了文件还没重新生成清单，第二次是改了 CHANGELOG 与 test_content_js.py 的注释后还没重新生成清单；每次重新生成后 `check_package --dir` 即通过。最终流程：全部文件定稿 → 重新生成 MANIFEST.json → 全量 219 项 0 失败 → 写本文件 → 再重新生成 MANIFEST.json（含本文件）→ 跑发布门。

### 17.4 全量原始输出（`tests/test-output-rc4.txt`，末尾汇总）

```
Ran 219 tests in 149.524s
OK
Tests run: 219, failures: 0, errors: 0, skipped: 0
SUITE: PASS
```
