# 已知限制（KNOWN-LIMITATIONS.md）

版本：v1.0.0-rc4，2026-11-19。本文件列出所有**尚未验证**或**有意不做**的事项。我们不把其中任何一项说成已通过。

## RC4 决定：Muse 审批卡不能授权执行（主动禁用）

**RC4 起，Muse 审批卡只是通知/展示通道，不能作为执行授权来源。** 原因是 store 没有平台 API 可以反查 approval_request_id 是否真的存在——收据只能验形状，不能验真伪，所以它不能作为执行授权的依据。`platform_receipt()` 调用即拒绝（`platform_receipt_disabled`），任何手写 muse_approval_card 收据的批准请求也被拒绝；执行检查门也只接受本地审批页通道批准的决策，直到平台能提供可验证的批准结果之前都保持禁用。执行授权的唯一通道是本地审批页（安装 PIN + 会话令牌 + 决策绑定的 nonce；执行时重新核对整条批准记录）。这对手机推送测试的意义：推送测试现在只验证“通知能不能到达 Leo”，不再验证“卡上点的批准能不能授权执行”。

## RC4 修正版交付：发布前检查（2026-11-19）

ChatGPT 审核第一份 RC4 ZIP 时说它收到的文件里缺 `transport/agent-relay-host.exe`（CONDITIONAL REJECT，唯一 P0；审批修复本身全部通过）。Dash 核对了实际交付的文件：.exe 在里面（224,515 字节，SHA-256 与 `transport/agent-relay-host.exe.sha256` 一致）；ChatGPT 算出的 ZIP 哈希与 Dash 公布的不同——它收到的不是交付的文件，最可能是下载/重新上传时 .exe 被剥掉了（杀毒软件隔离 ZIP 里的 .exe 是首要嫌疑）。修正版只补了一道发布前检查并重新打包，内容与第一份 RC4 相同，版本号仍为 1.0.0-rc4（不是 RC5）。

**发布前检查 `tests/check_package.py`**：核对包目录里 20 个安装必需文件都在；核对 .exe 的 SHA-256 与校验文件一致；给它一个 ZIP 路径时，同样核对 ZIP 内部这 20 个文件都在、且 ZIP 里的 .exe 哈希一致。任何一项不对就大声失败（非零退出）。**ZIP 只有在该检查对包目录和最终 ZIP 都通过之后才能发布；不通过不许发。** 检查本身有测试覆盖（`tests/test_check_package.py`，11 项，已并入 batch 3）。

**上传提醒**：请直接上传这个 ZIP 文件本身，不要先解压再重新打包；如果 .exe 再次消失，请检查杀毒软件的隔离区；上传后请把 ChatGPT 算出的 SHA-256 发回来，与公布的哈希核对——哈希一致才说明它收到的就是交付的文件。

## RC4-hotfix：修修正版 RC4 被拒的 4 个问题（2026-11-19，不升 RC5）

ChatGPT 审核修正版 RC4 后 CONDITIONAL REJECT（2026-11-19 23:54）：审批修复、EXE 打包、扩展固定 ID、110 项测试独立复现全部通过；4 个必修问题——(P0) ping / health / read_latest 的回复不带 response nonce，适配器按 nonce 匹配于是超时；(P0) `run.py` 的 `_project()` 不读 `project_status` 记录，pause / complete 不生效；(P1) 扩展 HOST_NAME 与 E2E 注册的 host 名不一致；(P1) `doSend()` 没确认消息进对话就返回 ok:true。ChatGPT 批准 hotfix 计划（23:57），不升 RC5。Hotfix 修了这 4 项：nonce 回显（ping / health / read_latest / send 全带 nonce）、状态机读最新状态并强制状态限制（PAUSED / COMPLETED / BLOCKED 拒绝 advance）、E2E 用测试扩展 + `.e2e` host 且真正跑 install.py / uninstall.py、send 确认区分 MESSAGE_SENT 与 RESPONSE_COMPLETED（确认不了返回 UNCERTAIN，绝不自动重发）。测试 139 项全部通过（见 `tests/TEST-RECORDS-v4.md` 第 13 节）。

**发布前检查 `tests/check_package.py`**：必需文件清单从 20 个加到 24 个（新增 `windows_e2e_test/make_test_extension.py` 与 4 个 hotfix 测试文件）；ZIP 只有在该检查对包目录和最终 ZIP 都通过之后才能发布；不通过不许发。

**上传提醒（同修正版）**：请直接上传 `agent-relay-skill-v1.0.0-rc4-hotfix.zip` 文件本身，不要先解压再重新打包；如果 .exe 再次消失，请检查杀毒软件的隔离区；上传后请把 ChatGPT 算出的 SHA-256 发回来，与公布的哈希核对。

## RC4-hotfix2：修 hotfix 被拒的 2 个逻辑问题 + 发布门强制化（2026-11-20，不升 RC5）

ChatGPT 审核第一份 hotfix 后 REJECT（2026-11-20 10:13）：它收到的文件只有 85 项、没有 `transport/agent-relay-host.exe`；Dash 当场重新核对交付的文件：86 项，.exe 在里面（224,515 字节，SHA-256 与公布一致）。**.exe 在传输途中第二次被剥掉了**（第一次是原 RC4）。打包本身两次都没坏，问题在下载/重新上传的链路，杀毒软件隔离 ZIP 里的 .exe 是首要嫌疑。Hotfix2 的回应是两件实事：第一，修掉 ChatGPT 指出的 2 个逻辑漏洞——read_latest 只认肯定确认的助手节点（删掉 "article" 兜底，确认不了就报 found:false，绝不猜；completion watch 同理）；send 确认先拍发送前快照，要求出现**新**节点才算 MESSAGE_SENT（新节点的 data-message-id 一起报 message_id），只有旧的相同文本、没有新节点时返回 UNCERTAIN。第二，发布门强制化：新增 `tests/release_gate.py`，发布流程必须跑它（见 `docs/INSTALL.md` 第 7 节）——生成清单 → 查包目录 → 建 ZIP → 查 ZIP → 全部通过才写 .sha256；任何一步失败都不写 .sha256、不留可发布的 ZIP。ZIP **里面**新增 `MANIFEST.json`（每个文件 + SHA-256 + file_count + total_bytes），接收方可以马上核对完整性，发现传输剥离。

**接收方核对方法（给 Leo / ChatGPT）**：(1) 先数 ZIP 里的条目数，对 `MANIFEST.json` 的 file_count（清单本身 + 测试输出文件不计在内，见清单里的 excluded 说明）；(2) 核对 `transport/agent-relay-host.exe` 在不在、它的 SHA-256 与 `transport/agent-relay-host.exe.sha256` 是否一致；(3) 把 ChatGPT 算出的 ZIP SHA-256 与我们公布的哈希核对——哈希一致才说明它收到的就是交付的文件。**如果 .exe 再次消失，请检查杀毒软件的隔离区，并直接上传这个 ZIP 文件本身，不要先解压再重新打包。** 清单故意不覆盖 `tests/test-output-*.txt`（每次跑测试字节都变），所以测试输出的哈希对不上不是问题；但安装必需文件与源码文件的哈希必须全对。

**上传提醒（同修正版与 hotfix）**：请直接上传 `agent-relay-skill-v1.0.0-rc4-hotfix2.zip` 文件本身，不要先解压再重新打包；如果 .exe 再次消失，请检查杀毒软件的隔离区；上传后请把 ChatGPT 算出的 SHA-256 发回来，与公布的哈希核对。

## RC4-hotfix4：修 ATTEMPT-07 的 3 个缺陷 + P1–P4（2026-11-20，不升 RC5）

ChatGPT 的 HOTFIX3 静态验收通过后，Windows 真机测试继续：ATTEMPT-05、ATTEMPT-06、ATTEMPT-07 均为部分通过（见下）。ATTEMPT-07（2026-11-20 21:21）留下三个缺陷：B2 真实发送其实成功了但系统仍报 send_unconfirmed；B3 页面上有回复但 read_latest 返回 found=false；B4 最小化后台发送未通过。Leo 于 21:24 授权修复。ChatGPT 的 ROUND-22 回复（21:31）批准修复范围，给出精确的源码位置，并正式把 **GATE-SEAMLESS-CONTINUITY**（无缝衔接）加为发布门（PENDING）。

Hotfix4 修了：B2 发送顺序（先填内容、等按钮出现、一次点击；按钮只在输入后才出现）、发送确认超时 10 秒 + 旁证信号（输入框已清空且 AI 开始回复）、health 在输入框为空时 ok:true、read_latest 的 textContent/父级容器回退 + 3 秒重试（不重新引入 "article" 兜底）、background.js 会话固定绑定（每站点/会话一个固定标签页）、BAT 的清单验证改用 Python JSON 解析（verify_manifest.py）+ %TEMP% 解析成长路径（resolve_long_path.py）+ 各阶段记开始时间与退出码、B5 拆为 B5-A/B5-B。**诚实标注：read_latest / send 修复只在模拟 DOM + 单元测试里验证过（本机没有真实 Chrome/Windows），真实页面验证需 ChatGPT 的 ATTEMPT-08 重测；至今没有采集到真实的回复节点 DOM 结构做独立确认，ROUND-22 给的是精确的疑似位置，不是已验证的最终根因。** 测试见 `tests/TEST-RECORDS-v4.md` 第 15 节。

**上传提醒（同修正版与 hotfix）**：请直接上传 `agent-relay-skill-v1.0.0-rc4-hotfix4.zip` 文件本身，不要先解压再重新打包；如果 .exe 再次消失，请检查杀毒软件的隔离区；上传后请把 ChatGPT 算出的 SHA-256 发回来，与公布的哈希核对。**另：ATTEMPT-07 用的 Leo 的日常 ChatGPT 账号（隔离 Chrome 内登录，非专用测试账号）——后续测试只能发预定义的非敏感测试消息；本包不含 Leo 的密码、Cookie、会话令牌或个人聊天内容。**

## RC4-hotfix5：修 ATTEMPT-08 的 BAT 解析缺陷 + B2 仍失败（2026-11-20，不升 RC5）

ChatGPT 的 HOTFIX4 静态验收通过（2026-11-20 22:54，ZIP SHA-256 `802babfc…` 一致，91 项，167/167 测试独立复现），但 ATTEMPT-08 部分通过、**未批准发布**：直接安装链通过（install.py、verify_manifest.py、Native Host 驱动退出码均为 0）；ASCII BAT 在真机上解析失败（第 66 行括号、第 85 行 REM %~f，且只修两处仍有控制流异常）；B2 真实发送仍失败（nonce `acfe5a6ddef42ce3`，Adapter 超时/UNCERTAIN，测试文本 `H4-B2-20261120-01` 仍在输入框里）。Leo 于 22:55 授权修复。

Hotfix5 修了：BAT 的 CMD 解析缺陷按整类修（块内消息去 ASCII 括号 + 去 `%~` 展开 + 各失败阶段不同退出码 10–21 + 回归测试 `tests/test_bat_cmd_safety.py`，它在 Hotfix4 ASCII 版上检出 10 处问题）；B2 发送（`waitForSendButton` 永不解析禁用按钮、`doSend` 填充后立即核实、新错误 `send_button_never_enabled`、只点已启用的按钮）；适配器晚到回执对账（`_wait_outbox` 只数完整行、`send()` 超时后最终扫描、新 `reconcile_send()` + `file_log.send_reconciled()`，晚到回执只有带非空 message_id 才升级为 delivered-late）。**诚实标注：B2 的深层原因（页面为什么没同步输入状态）未从证据证明——新错误码让 ATTEMPT-09 能诚实诊断它；send / BAT 修复只在模拟 DOM + 单元测试 + 代码检查里验证过（本机没有真实 Chrome/Windows），真实页面与真实 Windows CMD 解析验证需 ChatGPT 的 ATTEMPT-09 重测；至今没有采集到真实的回复节点 DOM 结构做独立确认。** 测试见 `tests/TEST-RECORDS-v5.md`。

**上传提醒（同修正版与 hotfix）**：请直接上传 `agent-relay-skill-v1.0.0-rc4-hotfix5.zip` 文件本身，不要先解压再重新打包；如果 .exe 再次消失，请检查杀毒软件的隔离区；上传后请把 ChatGPT 算出的 SHA-256 发回来，与公布的哈希核对。**另：ATTEMPT-08 用的仍是 Leo 的日常 ChatGPT 账号（隔离 Chrome 内登录，非专用测试账号）——后续测试只能发预定义的非敏感测试消息；本包不含 Leo 的密码、Cookie、会话令牌或个人聊天内容。**

## RC4-hotfix6：修 ATTEMPT-09 的 BAT 控制流 + B2/B3 误判 + B4 最小化发送（2026-11-21，不升 RC5）

ChatGPT 的 HOTFIX5 独立审计（2026-11-21 00:23）判 PARTIAL PASS / RELEASE BLOCKED：输入完整性通过（ZIP `0c9132f4…`、ASCII BAT `19d1e586…`、包内 BAT `ce8a45a0…` 均一致，94 项），静态 BAT 安全 6/6、batch 1 28/28、adapter 晚到回执 11/11，但 batch 2 超时 + test_content_js.py 没在时限内跑完（不得据此标 PASS）；直接安装链通过；四处失败：BAT 自动段 FAIL（再现——日志只有 init 就跳到 Cleanup，exit 2，安装没跑）；B2 FAIL（假阴性——消息与回复都在真页面上，Adapter 却报 send_unconfirmed/uncertain，nonce `bf6c31daea2fa05b`）；B3 FAIL（read_latest 返回 found=false，尽管 ACK 可见，nonce `1d46c42f31770568`）；B4 FAIL（最小化后台发送报 send_button_missing_after_input / not_sent，nonce `e6d1c25e383db40d`）。Leo 于 00:24 授权修复。ROUND 25 回复（00:39）补充：真实 DOM 结构没拿到（ChatGPT 不打扰桌面的前提下拿不到原始 HTML DOM）；两个 role 选择器仍是未验证的假设；ChatGPT 给了一段脱敏 DOM 采集代码；B4 输入框实际接受了输入、恢复后前台按钮可见，最小化时按钮是否渲染仍未证明。

Hotfix6 修了：P1——整块 BAT 废弃，阶段逻辑搬进 Python（`windows_e2e_test/e2e_runner.py` 阶段状态机 INIT → PREFLIGHT → INSTALL → MANIFEST → MKEXT → DRIVER → B → CLEANUP，失败即停，CLEANUP 只在安装真正完成时才调 uninstall.py；`run_e2e_test.bat` 现为 45 行薄入口，只找 Python、定位包目录、调 runner，ASCII 副本与它字节相同）；B2/B3——多策略识别（备用 role 属性选择器、回合容器、文本锚、回合后继兜底）+ 识别失败时附脱敏诊断盘点（绝不含消息内容）+ 回声防护，证据标准未降低；新增只读脱敏 DOM 采集器（content.js `doCollectDom` + adapter.py `collect_dom`，ROUND 25 的代码移植——ATTEMPT-10 用它采集真实结构）；B4——最小化按钮时间序列日志（before_input / after_input / during_wait / timeout 或 button_found + visibilityState），隐藏标签页按钮等待上限 10 秒（时间序列才是诊断，等待上限本身不是修复）。**诚实标注：识别 / 发送 / BAT 修复只在模拟 DOM + 单元测试里验证过（本机没有真实 Chrome/Windows），真实页面验证需 ChatGPT 的 ATTEMPT-10 重测；至今没有采集到真实的回复节点 DOM 结构——ROUND 25 的采集器是 ATTEMPT-10 采集它的工具，不是数据本身；batch 2 在 ATTEMPT-09 超时的问题是 ChatGPT 侧的运行环境时限，不是本包测试本身的失败——本包的 test_content_js.py 在本机约 98 秒跑完（84 项全过），仍在 120 秒超时内。** 测试见 `tests/TEST-RECORDS-v6.md`。

**上传提醒（同修正版与 hotfix）**：请直接上传 `agent-relay-skill-v1.0.0-rc4-hotfix6.zip` 文件本身，不要先解压再重新打包；如果 .exe 再次消失，请检查杀毒软件的隔离区；上传后请把 ChatGPT 算出的 SHA-256 发回来，与公布的哈希核对。**另：ATTEMPT-09 用的仍是 Leo 的日常 ChatGPT 账号（隔离 Chrome 内登录，非专用测试账号）——后续测试只能发预定义的非敏感测试消息；本包不含 Leo 的密码、Cookie、会话令牌或个人聊天内容。**

## RC4-hotfix7：修 Hotfix6 薄 BAT 的 `py -3` 引用启动缺陷（2026-11-21，不升 RC5）

ChatGPT 在新对话“继续Muse项目 Conversation?”（2026-11-21 10:17，思考 37 秒）核验 Hotfix6：ZIP 完整性、Manifest、EXE 已核验，静态测试与单元测试通过；但发现一个具体问题：薄入口 `windows_e2e_test/run_e2e_test.bat` 把 Python 命令存为 `py -3`（第 16 行），执行时却写成 `"!PY!"`（第 44 行）——CMD 会把带引号的 `"py -3"` 当成一个可执行文件名，自动测试无法启动；应优先修复，而不是直接宣告 Hotfix6 通过。Leo 于 10:33 授权修复。旧对话“读取Muse对话”太长、ChatGPT 容易运行出错，Leo 另开新对话，今后所有讨论集中在新对话里。

Hotfix7 修了：命令与参数分开存（`PY=py` + `PYARGS=-3`，兜底 `PY=python` + `PYARGS=` 为空），调用时命令不带引号（`!PY! !PYARGS! …`，PKG 路径仍带引号）；BAT 仍为 50 行薄入口（纯 ASCII，GOTO 跳转、无括号块、无 `:log` 子程序、只报退出码 10/11）。新增 3 项回归测试（`tests/test_bat_cmd_safety.py`，10 项 → 13 项），覆盖整类隐患：带引号变量作命令时其赋值不得含空格；py 分支调用必须解析为命令 `py` + 参数 `-3`；python 兜底分支必须解析为 plain `python` 且不含 `-3`。旧 Hotfix6 BAT 在这 3 项上全失败（第 44 行 `"!PY!"` 解析为 `'py -3'`；第一组 PY 赋值为 `'py -3'` 而非 `'py'`；旧 BAT 没有 PYARGS），新 BAT 全过。B2/B3/B4、adapter.py、content.js、background.js、e2e_runner.py、EXE 全部未动。**诚实标注：BAT 启动修复只在代码检查 + Linux 单元测试里验证过（本机没有真实 Windows CMD），真实 Windows 启动验证需 ChatGPT 的 ATTEMPT-10 重测；至今没有采集到真实的回复节点 DOM 结构。** 测试见 `tests/TEST-RECORDS-v7.md`。

**上传提醒（同修正版与 hotfix）**：请直接上传 `agent-relay-skill-v1.0.0-rc4-hotfix7.zip` 文件本身，不要先解压再重新打包；如果 .exe 再次消失，请检查杀毒软件的隔离区；上传后请把 ChatGPT 算出的 SHA-256 发回来，与公布的哈希核对。**另：ATTEMPT-10 用的仍是 Leo 的日常 ChatGPT 账号（隔离 Chrome 内登录，非专用测试账号）——后续测试只能发预定义的非敏感测试消息；本包不含 Leo 的密码、Cookie、会话令牌或个人聊天内容。**

## 未验证（按重要性排序）

1. **GATE-HITL：PENDING。** 关键决策的手机推送通知尚未完成验证。设计已定（审批卡只做通知 + 本地审批页批准 + 令牌 + toast + 暂停），审批强制检查已实现（`approvals/approvals.py`，RC4 只认本地审批页凭证，平台收据通道已禁用；自动化测试分批通过，含本地审批页真实服务器端到端测试与 PIN 锁定测试）。Leo 已于 2026-11-19 21:33 在手机上装好 Muse，手机审批推送测试已开始：Test 1（批准）已通过；Test 2（拒绝）与 Test 3（超时）待验证；审批卡是手机推送还是只在 App 内显示，尚未确认。真实通知是否到达手机、批准/拒绝/超时三种结果是否都按预期走，全部验证通过前保持 PENDING。
2. **GATE-AUTONOMY：PENDING。** 无人值守自主协作尚未通过独立验收。验收标准（见 `docs/GATES-v1.md` 与 `tests/acceptance_gates.md`）：Leo 只发起一次任务；Muse 与真实 ChatGPT 连续完成至少三轮实质讨论；过程中 Leo 不需要手动转发、复制粘贴或提示；双方消息、时间戳、轮次与最终结论全程可追溯；任务结束后自动生成一份供 Leo 决策的结论。安装/安全测试不能代替这项验收。v1 诚实地写成“Muse 驱动的自主讨论”，不宣称 ChatGPT 已具备自主唤醒能力。
3. **GATE-SEAMLESS-CONTINUITY：PENDING（新发布门，ROUND 22 加入）。** 无缝衔接尚未通过真实三轮连续验收。验收标准（见 `docs/GATES-v1.md` 与 `tests/acceptance_gates.md`）：每轮新开浏览器窗口数为 0、每轮新开标签页数为 0、连续 3 轮自主讨论全部完成、产品主动抢前台焦点的次数为 0、重连后继续已有讨论且不自动重发旧的 UNCERTAIN 消息。实现（Hotfix4）：background.js 会话固定绑定；模拟测试（15 项）已通过；ATTEMPT-08 验证了同一 tab ID `1527581763` 复用（会话绑定在标签页层面有效），ATTEMPT-09 验证了同一 tab ID `1527581903` 复用（health ok=true，tab_rebound=true），但真实三轮连续验收仍待 ATTEMPT-10。
4. **Muse handoff 自动唤醒：NOT YET IMPLEMENTED。** `orchestrator/run.py` 能推进状态、收发消息、做对账，但这不证明它能自动唤醒 Muse 会话并生成下一轮。每轮的模型步骤仍需一次 Muse 会话执行（定时任务唤醒或用户在场）。GATE-AUTONOMY 绝不能只凭 stub 测试标 PASS。
5. **长期无人值守运行：未验证。** 本次 POC 只跑了约 1 小时的讨论（多轮、用户不值守），更长时间的连续运行没有测过。
6. **断线后自动恢复：未验证。** 看门狗的设计已定，`watchdog.py` 脚本已在本地验证（新鲜/过期/缺失三种情况），但端到端“断线 → 看门狗发现 → 唤醒会话 → 续跑”的完整链路尚未验证。
7. **云电脑 SQLite 持久化、重启恢复与并发写入：未验证。** 因此 v1 默认权威来源是单写入者文件日志（`orchestrator/file_log.py`，RC2 已加严格去重与发送事务），不是 SQLite。`schema.sql` 已备好，只在三项验证通过后才升格为权威来源。
8. **事件驱动传输：未建成。** v1 用 15 秒轮询；ChatGPT 侧真正唤醒（Automations E1/E2）尚未开始验证；内容脚本 + 原生消息的后台提交方案尚未做条款检查（扩展代码本身已写好，见第 11 条）。
9. **系统级焦点日志：未采集。** GATE-NO-FOCUS 的 PASS 只覆盖当前测试环境（两次后台写入 + 用户亲眼确认 Chrome 未蹦到前台）。长期稳定性需补充系统级焦点日志。
10. **Relay 客户端只验证过本地 stub，未连过真实 Relay。** Relay 地址与令牌尚未提供；Tailscale 尚未加入（状态 Not connected）；Relay 侧“只有真实 ChatGPT 会话能以 sender=chatgpt 写入”的来源保证尚未验证（服务器端强制规则见 `transport/relay_spec.md`，Relay 服务器本身尚未实现）。
11. **Chrome 扩展已在真实 Chrome 里加载过，但选择器与真实页面往返尚未全部验证。** 扩展已在 Leo 的 Windows 隔离 Chrome 里加载（ATTEMPT-06 B1 通过；ATTEMPT-07 扩展通信通过），Native Host ↔ 扩展的健康检查通过。但 content.js 的选择器是否匹配**当前**真实 chatgpt.com / muse.ai 页面、Hotfix4/5/6 的发送/读取修复在真实页面上是否生效，均未验证（只在模拟 DOM + 单元测试里验证过），待 ATTEMPT-10。Hotfix6 新增只读脱敏 DOM 采集器（`collect_dom`）正是为 ATTEMPT-10 采集真实结构而设——至今没有采集到真实的回复节点 DOM 结构。扩展代码本身只做了语法与结构检查（`node --check`、manifest JSON 合法、最小权限、禁用能力扫描）。
12. **install.py / uninstall.py 已在真实 Windows 上跑过，但 run_e2e_test.bat 本身仍未在真实 Windows 上跑过修复后的版本。** install.py（测试 host 名）与手动运行的 uninstall.py 已在 ATTEMPT-05/06/07/08/09 的真实 Windows 上通过（安装与卸载、注册表写入与删除均按预期）；.bat 的延迟展开 bug 已在 RC3 修复。但 BAT 自动调 uninstall.py 曾因短路径失败（ATTEMPT-05），Hotfix4 的 P1 修复（长路径解析 + Python 清单验证）与 Hotfix5 的 P1 修复（块内消息去括号 + 去 `%~` + 不同退出码）尚未在真实 Windows 上跑过——ATTEMPT-08 交付的 ASCII BAT 在真机上解析失败（第 66 行括号、第 85 行 REM %~f，且只修两处仍有控制流异常），Hotfix5 按整类修了它；ATTEMPT-09 交付的 ASCII BAT 在真机上又从 init 直接跳到 Cleanup（exit 2，安装没跑），Hotfix6 把全部阶段逻辑搬进 Python（`e2e_runner.py` 阶段状态机 + 45 行薄 BAT 入口），Hotfix7 又修了薄 BAT 的 `py -3` 引用启动缺陷（PY/PYARGS 分开存、调用不带引号，50 行），待 ATTEMPT-10 真机验证。支持的安装路径仍是 SKILL.md 里的首次安装向导。
13. **Windows E2E：进行中（部分通过，未全部通过）。** agent-relay-host.exe 已在真实 Windows 上运行过（ATTEMPT-05/06/07/08/09，ChatGPT 用官方 Desktop Agent 操作 Leo 的 Windows 电脑）：隔离安装通过、真实 .exe 协议 8/8 通过、测试扩展加载通过、Chrome 启动 Native Host 通过、adapter.py → Chrome 健康检查通过、最小化后台健康检查通过（Chrome 未蹦到前台）。未通过/待定：B2 真实发送（ATTEMPT-06 为 UNCERTAIN；ATTEMPT-07 其实已发送成功但确认机制误判；ATTEMPT-08 仍失败——文本留在输入框，Adapter 超时/UNCERTAIN，nonce `acfe5a6ddef42ce3`；ATTEMPT-09 为**假阴性**——消息 `H5-B2-20261120-01` 与回复 `ACK-H5-B2-20261120-01` 都在真页面上，Adapter 却报 send_unconfirmed/uncertain，nonce `bf6c31daea2fa05b`）、B3 读 AI 回复（ATTEMPT-07 失败：页面上有回复但 read_latest 返回 found=false；ATTEMPT-08 无法继续；ATTEMPT-09 失败：ACK 可见但 read_latest 返回 found=false，nonce `1d46c42f31770568`）、B4 最小化后台发送（未通过；ATTEMPT-08 无法判定；ATTEMPT-09 失败：send_button_missing_after_input / not_sent，nonce `e6d1c25e383db40d`）、B5-A/B5-B（ATTEMPT-09 未重验）、三轮无人值守讨论（待定）。Hotfix6 修了 BAT 控制流（薄入口 + Python 阶段状态机）+ B2/B3 多策略识别与脱敏诊断 + 脱敏 DOM 采集器 + B4 按钮时间序列，Hotfix7 修了薄 BAT 的 `py -3` 引用启动缺陷（PY/PYARGS 分开、调用不带引号），待 ChatGPT 的 ATTEMPT-10 重测。另：run_e2e_test.bat 的清单检查（findstr）曾把路径/读取错误报成内容错（ATTEMPT-05/06 的日志自相矛盾）；Hotfix4 改为 Python JSON 解析（verify_manifest.py）+ 长路径解析（resolve_long_path.py），Hotfix5 再修了 BAT 的 CMD 解析缺陷（块内消息去括号 + 去 `%~` + 不同退出码），Hotfix6 把阶段逻辑搬进 Python；但 BAT 本身仍未在真实 Windows 上跑过修复后的版本。install.py / uninstall.py 的真实 Windows `winreg` 路径已在 ATTEMPT-05/06/07/08/09 里跑过（安装与手动卸载通过；BAT 自动调 uninstall.py 曾因短路径失败，见 Hotfix4 的 P1 修复；ATTEMPT-08 里 BAT 自动调 install 也失败，见 Hotfix5 的 P1 修复；ATTEMPT-09 里 BAT 从 init 直接跳到 Cleanup，见 Hotfix6 的 P1 修复）。
14. **Windows toast 推送：未验证。** 作为通知提醒是设计中的选项，需先检查用户机器的通知设置，再实测。
15. **本地审批页的 PIN 流程未在真实 Windows 上走过。** 服务器本身已在 Linux 上用真实 HTTP 请求端到端测过（错 PIN → 403、连续错 PIN → 锁定、锁定后对的 PIN 也拒绝、无会话 → 403、会话单次使用、错 nonce → 403、错令牌 → 403、过期会话 → 403），但在用户机器上从安装 PIN 生成到打开页面批准的整条路还没跑过。RC4 补了 PIN 防暴力破解（连续错 5 次锁定 15 分钟，锁定事件写审计日志），但这只是代码与测试，未在真实 Windows 上验证。

## 有意不做的（v1 边界）

16. **没有常驻后台程序。** 协调器是 Muse 会话 + `orchestrator/run.py` 入口；如果会话断了且提醒没到，讨论会悄悄停下，直到看门狗发现并报告。这是设计选择，不是 bug；v1 不装守护进程。
17. **ChatGPT 不能自发起。** v1 诚实地写成“Muse 驱动的自主讨论”，不宣称 ChatGPT 已具备自主唤醒能力。
18. **没有一键 .exe 安装器。** 首次安装是 Muse 会话里的向导（对话式），不是编译好的安装程序。`install.bat` 只是调用 `install.py` 的启动器。
19. **单用户。** v1 只服务一台 Windows 电脑上的一个用户（自己的 Chrome、自己的 ChatGPT、自己的 Muse）。多用户、共享状态不在 v1 范围内。
20. **不做实时队列。** GitHub 只放代码、版本化成果与审计，不承载实时消息队列；实时状态在文件日志/SQLite 里。

## 已验证的（对照）

见 `tests/TEST-RECORDS-v4.md`：定时唤醒、浏览器读、浏览器写、GATE-NO-FOCUS-WRITE-01（两次后台写入）、15 秒轮询、三轮实质讨论、Relay 客户端本地 stub 9/9、file_log.py 与 watchdog.py 本地验证，以及 RC4 的自动化测试（分批通过；file_log 去重与发送事务、locking、approvals 本地审批页凭证、relay_client stub、native_host 模拟往返、扩展语法与最小权限 + 固定 ID、run.py 冒烟 + 两种模式、本地审批页真实服务器端到端 + PIN 锁定、安装器/卸载器 FakeRegistry 测试）全部通过。
