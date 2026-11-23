# 测试记录（TEST-RECORDS-v2.md）

版本：v1.0.0-rc2。日期：2026-11-19（澳大利亚悉尼时间 AEDT）。本文件只记录已实际验证的内容；未验证的绝不写成已通过，见 `docs/KNOWN-LIMITATIONS.md`。第 1–8 节是 RC1 的实测记录（保留）；第 9 节是 RC2 的审核与自动化测试记录。

时间口径：所有时间以运行日志（cron 运行记录、浏览器任务实测时间）为准，不以 AI 自述时间为准。

## 1. 定时唤醒测试（2026-11-19 17:04–17:05）— PASS（带一个已说明的瑕疵）

- 任务：一次性定时任务，在指定 Muse 会话里读固定测试消息并现场生成一句新回复；不许用预写文本。
- 运行记录：run ID `18f20ebf-263e-4251-8309-b393b203ecde`，状态 succeeded；预定 17:04:00，实际开始 17:04:41，结束 17:05:06。
- 结果：A（定时任务跑了）PASS；B（会话实际被唤醒）PASS；C（模型实际生成回复）PASS，但有瑕疵——回复里写的时间是预定时间 17:04:00，不是实际开始时间 17:04:41，所以光看时间戳不能证明现场生成；证明靠的是运行记录 + 事先不存在任何预写回复文本。
- 清理：一次性任务已消耗，不会再跑，不占额度。

## 2. Chrome 读取验证（2026-11-19 20:26–20:29）— 读通路 PASS（走浏览器内置读取）

- 第一次尝试（20:26）失败：受控浏览器窗口报告“没有打开的标签页”，什么都没读到。不是 ChatGPT 拦截，是窗口里没有标签页。
- 第二次尝试（20:29）成功：Leo 分享了 ChatGPT 标签页（`chatgpt.com/c/6afe9d05…`，标题“读取Muse对话”）后，读到最新助手回复全文 514 字。
- 方法：浏览器内置页面读取（DOM + 文本视图），**不是** Muse for Chrome 扩展的 DOM 路径——扩展 DOM 路径本身仍未验证。
- 可见区域之外的回复不经滚动即可读到；读时 t1 已是活动标签页，未做激活操作；操作系统级前台焦点状态工具内测不出来。
- 结论：标签页被分享进受控窗口后，后台只读通路可用。

## 3. 写入 ChatGPT 测试（2026-11-19 20:32–20:33）— PASS

- 只发了授权的一条消息（带标记，要求回“收到，MUSE-TEST-1”）。
- ChatGPT 回复与要求一字不差：“收到，MUSE-TEST-1”，约 25 秒写完。
- 发送时 t1 已是活动标签页，未切换标签页或窗口；未观察到抢焦点（操作系统级焦点测不出来）；过程无问题。
- 结论：读 + 写一个来回走通了。

## 4. GATE-NO-FOCUS-WRITE-01（2026-11-19 20:42–20:43）— PASS（当前测试环境）

验收标准（三项同时成立）：消息真实送达；没有前台窗口切换；没有键盘鼠标抢占。

- MUSE-BG-WRITE-01（20:42）：Chrome 最小化状态下发送，约 15 秒后 ChatGPT 确认收到（127 字）。
- MUSE-BG-WRITE-02（20:43）：Leo 全程不动重跑一次，约 15 秒后 ChatGPT 确认收到（182 字）。
- 方法：全程只用 DOM 级填写 + DOM 级点击；未切换标签页或窗口；未恢复 Chrome；未用系统级键盘鼠标；未遇到需要激活的情况。
- 决定性证据：Leo 亲眼确认 Chrome 没有蹦到前台，最小化状态保持不变。
- ChatGPT 同意标记为 PASS（当前测试环境），并指出以后应补充系统级焦点日志以验证长期稳定性。

## 5. 15 秒轮询监控（2026-11-19 20:35–20:45）— 可用

- 监控开始 20:35，约 2 分 15 秒后（第 8 次每 15 秒检查）发现 ChatGPT 新回复（20:38，129 字，由 Leo 发给 ChatGPT 的“你和muse再打个招呼”触发）。
- 后台标签页读取已验证：新回复在可见区域之外，不经滚动、不切前台即可读到。
- 后续每次发送后约 15 秒即发现 ChatGPT 回复（20:40 的 532 字回复、20:45 的 799 字回复均在第一次 15 秒检查时发现）。
- 补充说明：浏览器监控任务每次报一条新回复就结束，不会自己跑满 30 分钟；连续监控靠每轮重新发起任务（handoff 接续）。

## 6. 三轮实质讨论 RELAY-AUTONOMY-POC-01（2026-11-19 20:52–20:55）— 已收敛

- 第一轮：Muse 发协议与题目（20:52）；ChatGPT 回架构提案（20:52，1935 字）：独立 Skill、五层、五模块、状态机、交付分工。
- 第二轮：Muse 回六点意见（20:53）：浏览器任务适配器边界、看门狗、GitHub 做规范状态库、审批与通知复用、分工、最可能失败的三个问题。
- 第三轮：ChatGPT 回架构收敛与定稿（20:54 发现、20:55 确认写完，1970 字）：六项裁决——同意 Muse 驱动、浏览器任务加 handoff 接续、看门狗（只报警或有限恢复）；**不同意 GitHub 做唯一规范状态库**（GitHub 只放代码、成果与审计，不做实时队列）；有条件同意 Muse 审批卡与通知（手机推送与身份绑定必须实测）；同意 Muse/Codex 分工、ChatGPT 保留独立审查。最终状态库决定：云电脑 SQLite 为权威来源（须先验证持久化、重启恢复、并发写入，否则先用单写入者文件日志）；GitHub 私有仓库只放脱敏成果；Windows 本地只做缓存与日志。
- 第四轮：Leo 决策（21:06，六点：批准；继续讨论出完整稳定方案；Dash 直接制作，不交 Codex；操作傻瓜化；Chrome 扩展只是 skill 里的一个环节；手机 Muse 待安装）；Muse 同步决定请 ChatGPT 给最终意见（21:07）；ChatGPT 回复：设计已冻结、同意实施、无需第五轮。
- 讨论全程记录：`~/workspace/agent-relay/discussion/relay-autonomy-poc-01.md`（本包未收录，为 Leo 的本地记录）。

## 7. Relay 客户端本地验证（2026-11-19，修订版）— 9 项全部通过

用本地 stub 服务器（127.0.0.1）模拟 Relay，不连真实 Relay：

1. health 正常；2. next 取到 ChatGPT 消息（turn_number 与 source_session 保留）；3. reply 提交成功；4. 重复回复被本地拦截（stub 只收到 1 次 POST）；5. get 正常；6. sender=codex 的消息被拒绝（untrusted_sender，退出码 1）；7. 空队列返回空；8. 缺 Token 干净报错（退出码 2）；9. 500 后重试成功。
- Token 在任何客户端输出中出现 0 次。验证用的回复文本是固定测试字符串，仅用于验证传输路径；真实联调中的回复一律由模型现场生成。
- 注意：客户端只验证过本地 stub，未连过真实 Relay；Relay 地址与令牌尚未提供，tailnet 尚未加入（Tailscale 状态：Not connected，2026-11-19 17:20 复查）。

## 8. 本包新增脚本的本地验证（2026-11-19）

- `orchestrator/file_log.py`：追加两条记录（seq 1、2）成功；count=2；verify 通过；篡改内容后 verify 报 hash_mismatch + length_mismatch（退出码 1）；超 8000 字内容被拒绝（退出码 1）。
- `orchestrator/watchdog.py`：新鲜心跳 → ok（退出码 0）；20 分钟前的心跳 → stale（退出码 1）；缺失文件 → missing（退出码 2）。
- `transport/install.bat`：未在 Windows 上实测（见 docs/KNOWN-LIMITATIONS.md）；支持的安装路径是 SKILL.md 里的首次安装向导。

## 9. RC2：ChatGPT 独立审核 RC1 的结论与 RC2 修复验证（2026-11-19 21:27–21:29）

### 9.1 ChatGPT 对 RC1 的审核结论：REJECT（不是设计或浏览器通信被否）

- 通过项：ZIP 完整性（53,499 bytes，SHA-256 对得上）；Python 语法（4 个脚本）；架构与协议文档可作 RC2 基础。
- 必须修（P0）：没有可执行的浏览器适配器（只有 browser_adapter.md 描述 DOM 方法，没有代码/扩展）；没有自动协作执行入口（orchestrator.md 只有步骤，没有可运行的循环）；审批只是文档（没有令牌校验器、状态机、执行前强制检查）。
- 必须修（P1）：install.bat 目录路径错误（在 agent-relay-skill/ 里却找旁边的另一个 agent-relay-skill，双击必失败）；卸载备份没有失败检查；状态日志没有严格去重 + 发送事务保护；测试证据不够独立。
- 安全问题：file_log.py 按时间删旧锁（活着的写入者可能与第二个写入者冲突）；relay_client.py 的 sender=="chatgpt" 检查只能核对声明的身份，不能证明消息真的来自 ChatGPT 会话（需要可信服务器或浏览器会话来源保证）。
- ChatGPT 的任务：建 v1.0.0-rc2，不再讨论架构，不交 Codex；保持三步流程；手机审批等 Leo 装好手机端 Muse，GATE-HITL 保持 PENDING，审批没通过的执行默认全部拦截。
- Muse 回复（第 5 轮，21:27）：接受结论，提出逐项 RC2 修复计划（真实 Chrome 扩展适配器；orchestrator/run.py 入口；approvals/approvals.py 强制检查；修 install/uninstall；文件日志去重 + 事务 + 跨平台锁；按参与方发 Relay 令牌 + origin 绑定扩展来源），请 ChatGPT 先确认再开工。
- ChatGPT 回复（21:28，1408 字）：RC2 IMPLEMENTATION APPROVED——直接开工，无需再确认；附 5 条额外验收条件（扩展最小权限；扩展↔协调器真实连接；审批令牌绑定到具体操作 + 可信独立审批通道；保守的发送失败恢复，UNCERTAIN 状态 + 暂停；Muse handoff 诚实标注——run.py 推进状态不证明能自动唤醒 Muse）。目标：一次修完所有已知阻塞点，不再出一个只改文档、只做模拟的候选版。

### 9.2 RC2 修复了什么（与 §9.1 逐项对应）

- P0-1：`transport/extension/` 真实 Chrome 扩展（manifest.json、content.js、background.js）：DOM 读/写、回复写完检测（MutationObserver，3 秒无变化 + 停止按钮消失）、不抢焦点/键盘/鼠标；`transport/adapter.py` 是 Muse 侧可调用的适配器接口（health / read_latest / send / poll / verify + 验证记录）。
- P0-2：`orchestrator/run.py` 可运行入口（create / advance / resume / reconcile / record-send / pause / complete / status）；回复文本仍由 Muse 会话现场生成，run.py 绝不编造；status 输出每次都写明 handoff 自动唤醒为 NOT YET IMPLEMENTED。
- P0-3：`approvals/approvals.py`（令牌仪式 + 状态机 pending → approved/rejected/expired + 执行前检查门）；测试证明：批准一次 → 允许；重放 → 拒绝；过期 → 拒绝；无批准 → 拒绝；聊天文本/Relay 内容通道 → 拒绝。
- P1-1：install.bat 路径 bug 已确认并修复（同时支持“bat 在 skill 文件夹里”和“bat 在文件夹旁边”两种位置）；路径模拟验证见 §9.4；真实 Windows 验证仍为 PENDING。
- P1-2：uninstall.bat 备份后检查 robocopy 退出码（8 及以上 = 失败 → 拒绝删除）；删除前核对目标确实是 skill 文件夹（路径含 agent-relay-skill 且有 SKILL.md）。
- P1-3：file_log.py 严格去重（message_id / nonce 唯一，重复拒绝）+ 发送事务（intent → send → success/failed）+ 重启对账（核实不了 → UNCERTAIN 并暂停，绝不自动重发）。
- P1-4：`tests/run_tests.py` 自动化套件（见 §9.3），原始输出见下。
- Security-1：`orchestrator/locking.py` 跨平台操作系统锁（POSIX fcntl / Windows msvcrt），锁文件永不删除；只有在确认持有者进程已死时才允许抢锁，判断不出来时宁可超时也不抢。
- Security-2：`transport/relay_spec.md`（Relay 按参与方发令牌、服务器端强制 sender 与令牌一致，不一致 → 403）；扩展来源绑定到页面 origin（chatgpt.com 标签页读到的回复就是 sender=chatgpt）。

### 9.3 RC2 自动化测试套件（2026-11-19，本地）— 50 项全部通过

运行：`python3 tests/run_tests.py`。范围：file_log（13 项：追加/篡改/超长/去重/发送事务/对账/UNCERTAIN）、watchdog（5 项）、locking（2 项：第二写入者超时而非抢锁、释放后可重取）、approvals（14 项：批准一次/重放/过期/无批准/错令牌/错通道/错选项/参数摘要不符/操作 ID 不符/拒绝流程/令牌不明文/本地审批页通道）、relay_client 对本地 stub（3 项：9 项序列/缺令牌/500 重试）、native_host 往返（6 项：协调器→扩展转发/扩展→协调器记录/ping 往返/错 secret 拒绝/secret 文件 0600/stdin 关闭后退出）、extension 语法与最小权限（4 项：manifest 合法且最小/JS 语法/无禁用能力/host 清单模板）、run.py 冒烟（3 项：建项目→handoff→补录→状态诚实块/UNCERTAIN 暂停/未知项目）。

原始输出（`tests/test-output-rc2.txt`，逐字）：

```
Agent Relay Skill v1.0.0-rc2 — automated test suite
============================================================

[1/2] py_compile all Python files in the package
py_compile: PASS

[2/2] unittest suite
test_append_count_verify (test_file_log.TestFileLogBasics.test_append_count_verify) ... ok
test_oversize_content_rejected (test_file_log.TestFileLogBasics.test_oversize_content_rejected) ... ok
test_tamper_detected (test_file_log.TestFileLogBasics.test_tamper_detected) ... ok
test_duplicate_intent_rejected (test_file_log.TestFileLogDedup.test_duplicate_intent_rejected) ... ok
test_duplicate_message_id_rejected (test_file_log.TestFileLogDedup.test_duplicate_message_id_rejected) ... ok
test_duplicate_nonce_rejected (test_file_log.TestFileLogDedup.test_duplicate_nonce_rejected) ... ok
test_confirm_without_intent_rejected (test_file_log.TestSendTransaction.test_confirm_without_intent_rejected) ... ok
test_duplicate_outcome_rejected (test_file_log.TestSendTransaction.test_duplicate_outcome_rejected) ... ok
test_intent_then_success (test_file_log.TestSendTransaction.test_intent_then_success) ... ok
test_reconcile_no_verify_fn_marks_uncertain (test_file_log.TestSendTransaction.test_reconcile_no_verify_fn_marks_uncertain) ... ok
test_reconcile_not_sent (test_file_log.TestSendTransaction.test_reconcile_not_sent) ... ok
test_reconcile_sent (test_file_log.TestSendTransaction.test_reconcile_sent) ... ok
test_reconcile_unknown_marks_uncertain (test_file_log.TestSendTransaction.test_reconcile_unknown_marks_uncertain) ... ok
test_bad_timestamp (test_watchdog.TestWatchdog.test_bad_timestamp) ... ok
test_corrupt (test_watchdog.TestWatchdog.test_corrupt) ... ok
test_fresh_is_ok (test_watchdog.TestWatchdog.test_fresh_is_ok) ... ok
test_missing (test_watchdog.TestWatchdog.test_missing) ... ok
test_stale (test_watchdog.TestWatchdog.test_stale) ... ok
test_reacquire_after_release (test_locking.TestFileLock.test_reacquire_after_release) ... ok
test_second_writer_times_out_instead_of_stealing (test_locking.TestFileLock.test_second_writer_times_out_instead_of_stealing) ... ok
test_approve_once_then_execution_allowed (test_approvals.TestApprovals.test_approve_once_then_execution_allowed) ... ok
test_expire_overdue (test_approvals.TestApprovals.test_expire_overdue) ... ok
test_expired_token_denied (test_approvals.TestApprovals.test_expired_token_denied) ... ok
test_local_approval_page_channel_allowed (test_approvals.TestApprovals.test_local_approval_page_channel_allowed) ... ok
test_no_approval_denied (test_approvals.TestApprovals.test_no_approval_denied) ... ok
test_operation_id_mismatch_denied (test_approvals.TestApprovals.test_operation_id_mismatch_denied) ... ok
test_params_digest_mismatch_denied (test_approvals.TestApprovals.test_params_digest_mismatch_denied) ... ok
test_reject_flow_blocks_execution (test_approvals.TestApprovals.test_reject_flow_blocks_execution) ... ok
test_replay_approve_denied_and_counted (test_approvals.TestApprovals.test_replay_approve_denied_and_counted) ... ok
test_second_execution_denied (test_approvals.TestApprovals.test_second_execution_denied) ... ok
test_token_never_stored_in_plain (test_approvals.TestApprovals.test_token_never_stored_in_plain) ... ok
test_untrusted_channel_denied (test_approvals.TestApprovals.test_untrusted_channel_denied) ... ok
test_wrong_option_denied (test_approvals.TestApprovals.test_wrong_option_denied) ... ok
test_wrong_token_denied (test_approvals.TestApprovals.test_wrong_token_denied) ... ok
test_flaky_health_retries (test_relay_client.TestRelayClient.test_flaky_health_retries) ... ok
test_full_sequence (test_relay_client.TestRelayClient.test_full_sequence) ... ok
test_missing_token_clean_error (test_relay_client.TestRelayClient.test_missing_token_clean_error) ... ok
test_bad_auth_refused (test_native_host.TestNativeHost.test_bad_auth_refused) ... ok
test_coordinator_to_extension_forward (test_native_host.TestNativeHost.test_coordinator_to_extension_forward) ... ok
test_extension_to_coordinator_recorded (test_native_host.TestNativeHost.test_extension_to_coordinator_recorded) ... ok
test_host_exits_on_stdin_close (test_native_host.TestNativeHost.test_host_exits_on_stdin_close) ... ok
test_ping_round_trip (test_native_host.TestNativeHost.test_ping_round_trip) ... ok
test_secret_file_mode_0600 (test_native_host.TestNativeHost.test_secret_file_mode_0600) ... ok
test_js_syntax_with_node (test_extension_syntax.TestExtension.test_js_syntax_with_node) ... ok
test_manifest_valid_and_minimal (test_extension_syntax.TestExtension.test_manifest_valid_and_minimal) ... ok
test_native_host_manifest_template (test_extension_syntax.TestExtension.test_native_host_manifest_template) ... ok
test_no_forbidden_capabilities (test_extension_syntax.TestExtension.test_no_forbidden_capabilities) ... ok
test_create_advance_record_status (test_run.TestRunPy.test_create_advance_record_status) ... ok
test_reconcile_with_uncertain_pauses (test_run.TestRunPy.test_reconcile_with_uncertain_pauses) ... ok
test_unknown_project (test_run.TestRunPy.test_unknown_project) ... ok

----------------------------------------------------------------------
Ran 50 tests in 9.173s

OK

Tests run: 50, failures: 0, errors: 0, skipped: 0
SUITE: PASS
```

补充说明：第一次跑套件时 1 项失败（test_no_forbidden_capabilities：content.js 开头注释里写了“never eval()ed”，被当成代码里的 eval( 误报）。修复：测试改为只去掉块注释再检查（行注释保留，避免把 `https://` 里的 `//` 也去掉而漏检）。重跑后 50/50 通过。失败与修复过程如实记录于此，不隐瞒。

### 9.4 install.bat / uninstall.bat 路径模拟验证（2026-11-19，本地，无 Windows）

- RC1 bug 复现：bat 在 agent-relay-skill/ 里时，RC1 的 `SRC=%~dp0agent-relay-skill` 解析为 `agent-relay-skill/agent-relay-skill`，不存在 → 双击必报错。模拟确认。
- RC2 修复验证：两种位置都模拟过——bat 在 skill 文件夹里（解压后的正常位置）解析为文件夹本身，存在；bat 在文件夹旁边解析为旁边的 skill 文件夹，存在。两种都对。
- uninstall 删除守卫模拟：目标是真实 skill 文件夹 → 通过；目标是别的路径 → 拒绝。备份失败检查（robocopy 退出码 ≥8 → BACKUP_OK=0 → 拒绝删除）为代码走查，未在真实 Windows 上跑过，见 `docs/KNOWN-LIMITATIONS.md`。

### 9.5 RC2 仍未验证 / 只模拟过的事项（诚实范围）

- 扩展代码只做了语法与结构检查（`node --check`、manifest JSON、禁用能力扫描），**没有在真实 Chrome 里加载测试**（本机没有 Windows Chrome）；选择器是否匹配真实 chatgpt.com / muse.ai 页面、native host 注册流程、扩展↔协调器在真实 Chrome 里的往返，均未验证。
- native host ↔ 扩展的往返是**本地模拟**（测试脚本扮演扩展那一端，拉起 host、发消息、读回复）；真实 Chrome 的 Native Messaging 端口未接过。
- install.bat / uninstall.bat 未在真实 Windows 上跑过（只做了路径模拟 + 代码走查）。
- Relay 服务器本身尚未实现；relay_spec.md 的服务器端强制规则未在真实 Relay 上验证；Tailscale 未加入；Relay 地址与令牌尚未提供。
- Muse handoff 自动唤醒：NOT YET IMPLEMENTED（run.py 推进状态不证明能自动唤醒 Muse；GATE-AUTONOMY 不能只凭 stub 测试标 PASS）。
- GATE-HITL：PENDING。Leo 已于 2026-11-19 21:33 在手机上装好 Muse，手机审批推送测试已开始（Test 1 批准路径进行中），批准/拒绝/超时三种结果全部验证通过前保持 PENDING。
