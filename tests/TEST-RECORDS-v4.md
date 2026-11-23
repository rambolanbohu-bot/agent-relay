# 测试记录（TEST-RECORDS-v4.md）

版本：v1.0.0-rc4。日期：2026-11-19（澳大利亚悉尼时间 AEDT）。本文件只记录已实际验证的内容；未验证的绝不写成已通过，见 `docs/KNOWN-LIMITATIONS.md`。第 1–8 节是 RC1 的实测记录（保留）；第 9 节是 RC2 的审核与自动化测试记录（保留）；第 10 节是 RC3 的审核与自动化测试记录（保留）；第 11 节是 RC4 的审核与自动化测试记录。

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

## 10. RC3：ChatGPT 有条件批准 RC3 计划与 RC3 修复验证（2026-11-19 21:52–）

### 10.1 ChatGPT 对 RC2 的审核结论：有条件批准 RC3 计划（不是 REJECT）

ChatGPT 2026-11-19 21:52（1270 字）有条件批准 RC3 计划：直接开建，不用再讨论架构，不交给 Codex。两个技术修正是强制的，另有安装器安全要求；其他已同意的部分（扩展最小权限、安装脚本修复、自动生成 host 清单、自动注册表配置、真实 Chrome 集成）按计划做。

### 10.2 Correction 1：Native Messaging Host 必须是真正的 .exe

- 做了什么：`transport/agent-relay-host.exe`（C 启动器，`transport/native_host/agent-relay-host.c`），Chrome 拉起它，它再拉起同目录的 `native_host.py`，stdin/stdout 原样透传协议。host 清单的 path 永远指向这个 .exe，绝不指向 .bat 或 .py。
- 怎么验证的（Linux 上交叉编译，mingw-w64 13-win32）：
  - `x86_64-w64-mingw32-gcc -O2 -mwindows -municode -Wall -o agent-relay-host.exe agent-relay-host.c`：编译干净，无警告。
  - `file agent-relay-host.exe`：`PE32+ executable (GUI) x86-64, for MS Windows`。
  - `objdump -p`：导入表只有 `KERNEL32.dll` 与 `msvcrt.dll`；KERNEL32 导入只有 CloseHandle、CreateFileW（日志）、CreateProcessW、GetExitCodeProcess、GetFileAttributesW、GetLastError、GetLocalTime、GetModuleFileNameW、GetStdHandle、SearchPathW、SetFilePointer、WaitForSingleObject、WriteFile——无注册表、无网络、无 shell 执行。
  - 字符串检查：没有 `.bat` / `cmd.exe` / `powershell`；宽字符字符串里有 `py.exe`、`python.exe`、`native_host.py`、`--state-dir`、`orchestrator\state\native_host`。
  - 源码里唯一写文件的地方是出错时写 `agent-relay-host.log`（绝不写 stdout；stdout 是协议通道）。
  - SHA-256：见 `transport/agent-relay-host.exe.sha256`。
- 还没验证的：这个 .exe 还没有在真实 Windows 上运行过（本机没有 Windows、没有 wine）。Windows E2E 在实测通过前不标 PASS。
- Windows 上重编：`transport/native_host/build_host_exe.bat`（mingw-w64 gcc 或 MSVC cl）。

### 10.3 Correction 2：审批重做——通道再也不能是调用者随手写的字符串

- 做了什么：`approvals/approvals.py` 只接受通道发出的凭证。Muse 审批卡通道用 `platform_receipt()`（收据必须含 approval_request_id、decision == "approved"、decided_by、decided_at，只允许用平台实际返回的批准结果构造）；本地审批页通道用 `approvals/local_approval_page.py`（只监听 127.0.0.1；安装 PIN + 单次会话令牌 + 与决策绑定的防伪 nonce）。旧的 `--channel` / `--approver` 命令行参数已删除；传裸字符串当 channel 一律拒绝。批准记录里的 approver 来自凭证收据，且必须与期望审批人一致。
- 两种模式（RC3）：Discussion（默认，只讨论，不执行任何对外生效的操作）与 Execution（需要项目切到 execution 模式 + 可信通道批准绑定到具体操作、参数摘要与审批人；默认拒绝；白名单目前只有 write_file，路径必须留在项目目录内）。
- 测试：`tests/test_approvals.py` 22 项（调用者随手写的通道字符串 → 拒绝；收据缺字段 → 拒绝；会话令牌未登记/已用过/过期 → 拒绝；nonce 不符 → 拒绝；审批人不符 → 拒绝；其余 RC2 行为不变）；`tests/test_local_page.py` 8 项（真实服务器端到端：错 PIN → 403、无会话 → 403、会话单次使用、错 nonce → 403、错令牌 → 403、拒绝流程、PIN 只存哈希）；`tests/test_run.py` 6 项两种模式测试（讨论模式拒绝执行、无批准拒绝执行、有批准写文件成功且只执行一次、路径逃逸拒绝、非白名单动作拒绝、status 报模式与 .exe 状态）。

### 10.4 安装器安全

- 做了什么：`install.py`（`install.bat` 调用）先检查再动手——目标已存在拒绝；注册表项已存在且指向别处时，交互先问、非交互拒绝；任何一步失败回滚；写安装清单（`install-manifest.json`）。`uninstall.py`（`uninstall.bat` 调用）只清理清单里的资源；注册表项只在它仍指向本次安装时才删，安装时覆盖过的旧值恢复回去；备份失败拒绝删除。
- 扩展 ID 固定：`manifest.json` 加了固定公开 key，扩展 ID 固定为 `jeelmedmciafjnfdpnjgbgipplcddhka`（私钥没有放进包里）；安装器直接用它生成 host 清单，用户不用手动查 ID、改 JSON、改注册表。扩展权限加了 `tabs`（background.js 调 `chrome.tabs.query()` 需要）。
- .bat 延迟展开 bug（RC2 里漏网的，已确认）：install.bat 与 uninstall.bat 在同一个括号块里先 set 再用 %VAR% 读到旧值（空）。RC3 里两个 .bat 改成 thin wrapper（调用 install.py / uninstall.py），并用 `setlocal EnableDelayedExpansion` + `!VAR!`，不再在块内读写同一个变量。逻辑走查：install.bat 里 PY 在 if/else 块内 set、块外用 !PY! 读；SRC 在块外 set、块外读；RC 在调用后 set、下一条语句用 !RC! 读。uninstall.bat 同样。安装器单元测试（FakeRegistry）覆盖了检查、拒绝、回滚、卸载。
- 测试：`tests/test_install.py` 15 项（安装 8 项：正常路径、目标已存在拒绝、注册表冲突非交互拒绝/用户拒绝/用户确认并记录旧值、.exe 缺失拒绝、回滚、check-only；卸载 7 项：正常路径、恢复旧值、注册表被改过则留着、无线上清单拒绝、非 skill 目标拒绝、保留状态备份、备份失败拒绝）。

### 10.5 RC3 自动化测试套件（2026-11-19，本地）— 88 项全部通过

命令：`python3 tests/run_tests.py`（输出见 `tests/test-output-rc3.txt`，下面是原始输出全文）。

```
Agent Relay Skill v1.0.0-rc3 — automated test suite
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
test_approver_mismatch_denied (test_approvals.TestApprovals.test_approver_mismatch_denied) ... ok
test_caller_declared_channel_string_denied (test_approvals.TestApprovals.test_caller_declared_channel_string_denied) ... ok
test_expire_overdue (test_approvals.TestApprovals.test_expire_overdue) ... ok
test_expired_token_denied (test_approvals.TestApprovals.test_expired_token_denied) ... ok
test_local_page_credential_allowed (test_approvals.TestApprovals.test_local_page_credential_allowed) ... ok
test_no_approval_denied (test_approvals.TestApprovals.test_no_approval_denied) ... ok
test_operation_id_mismatch_denied (test_approvals.TestApprovals.test_operation_id_mismatch_denied) ... ok
test_page_session_expired_denied (test_approvals.TestApprovals.test_page_session_expired_denied) ... ok
test_page_session_single_use (test_approvals.TestApprovals.test_page_session_single_use) ... ok
test_page_session_unknown_token_denied (test_approvals.TestApprovals.test_page_session_unknown_token_denied) ... ok
test_page_session_wrong_nonce_denied (test_approvals.TestApprovals.test_page_session_wrong_nonce_denied) ... ok
test_params_digest_mismatch_denied (test_approvals.TestApprovals.test_params_digest_mismatch_denied) ... ok
test_platform_receipt_factory_rejects_bad_input (test_approvals.TestApprovals.test_platform_receipt_factory_rejects_bad_input) ... ok
test_platform_receipt_missing_fields_denied (test_approvals.TestApprovals.test_platform_receipt_missing_fields_denied) ... ok
test_reject_flow_blocks_execution (test_approvals.TestApprovals.test_reject_flow_blocks_execution) ... ok
test_replay_approve_denied_and_counted (test_approvals.TestApprovals.test_replay_approve_denied_and_counted) ... ok
test_second_execution_denied (test_approvals.TestApprovals.test_second_execution_denied) ... ok
test_status_hides_token_hash_and_nonce (test_approvals.TestApprovals.test_status_hides_token_hash_and_nonce) ... ok
test_token_never_stored_in_plain (test_approvals.TestApprovals.test_token_never_stored_in_plain) ... ok
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
test_fixed_extension_id_matches_key (test_extension_syntax.TestExtension.test_fixed_extension_id_matches_key)
The manifest carries a fixed public key; Chrome derives the ... ok
test_js_syntax_with_node (test_extension_syntax.TestExtension.test_js_syntax_with_node) ... ok
test_manifest_valid_and_minimal (test_extension_syntax.TestExtension.test_manifest_valid_and_minimal) ... ok
test_native_host_manifest_template (test_extension_syntax.TestExtension.test_native_host_manifest_template) ... ok
test_no_forbidden_capabilities (test_extension_syntax.TestExtension.test_no_forbidden_capabilities) ... ok
test_create_advance_record_status (test_run.TestRunPy.test_create_advance_record_status) ... ok
test_reconcile_with_uncertain_pauses (test_run.TestRunPy.test_reconcile_with_uncertain_pauses) ... ok
test_unknown_project (test_run.TestRunPy.test_unknown_project) ... ok
test_execute_allowed_with_approval_writes_file (test_run.TestTwoModes.test_execute_allowed_with_approval_writes_file) ... ok
test_execute_non_whitelisted_action_refused (test_run.TestTwoModes.test_execute_non_whitelisted_action_refused) ... ok
test_execute_path_escape_refused (test_run.TestTwoModes.test_execute_path_escape_refused) ... ok
test_execute_refused_in_discussion_mode (test_run.TestTwoModes.test_execute_refused_in_discussion_mode) ... ok
test_execute_refused_without_approval (test_run.TestTwoModes.test_execute_refused_without_approval) ... ok
test_status_reports_mode_and_exe (test_run.TestTwoModes.test_status_reports_mode_and_exe) ... ok
test_approve_without_session_denied (test_local_page.TestLocalPage.test_approve_without_session_denied) ... ok
test_full_flow_approve_then_gate_allows (test_local_page.TestLocalPage.test_full_flow_approve_then_gate_allows) ... ok
test_pin_file_stores_only_hash (test_local_page.TestLocalPage.test_pin_file_stores_only_hash) ... ok
test_reject_flow (test_local_page.TestLocalPage.test_reject_flow) ... ok
test_session_single_use (test_local_page.TestLocalPage.test_session_single_use) ... ok
test_wrong_nonce_denied (test_local_page.TestLocalPage.test_wrong_nonce_denied) ... ok
test_wrong_pin_no_session (test_local_page.TestLocalPage.test_wrong_pin_no_session) ... ok
test_wrong_token_denied (test_local_page.TestLocalPage.test_wrong_token_denied) ... ok
test_check_only (test_install.TestInstall.test_check_only) ... ok
test_happy_path (test_install.TestInstall.test_happy_path) ... ok
test_refuses_registry_conflict_non_interactive (test_install.TestInstall.test_refuses_registry_conflict_non_interactive) ... ok
test_refuses_when_dest_exists (test_install.TestInstall.test_refuses_when_dest_exists) ... ok
test_refuses_when_exe_missing (test_install.TestInstall.test_refuses_when_exe_missing) ... ok
test_registry_conflict_user_confirms_records_prior (test_install.TestInstall.test_registry_conflict_user_confirms_records_prior) ... ok
test_registry_conflict_user_says_no (test_install.TestInstall.test_registry_conflict_user_says_no) ... ok
test_rollback_on_failure (test_install.TestInstall.test_rollback_on_failure) ... ok
test_happy_path (test_install.TestUninstall.test_happy_path) ... ok
test_keep_state_backs_up (test_install.TestUninstall.test_keep_state_backs_up) ... ok
test_keep_state_backup_failure_refuses (test_install.TestUninstall.test_keep_state_backup_failure_refuses) ... ok
test_leaves_registry_alone_if_changed (test_install.TestUninstall.test_leaves_registry_alone_if_changed) ... ok
test_refuses_non_skill_target (test_install.TestUninstall.test_refuses_non_skill_target) ... ok
test_refuses_without_manifest (test_install.TestUninstall.test_refuses_without_manifest) ... ok
test_restores_prior_registry_value (test_install.TestUninstall.test_restores_prior_registry_value) ... ok

----------------------------------------------------------------------
Ran 88 tests in 14.969s

OK

Tests run: 88, failures: 0, errors: 0, skipped: 0
SUITE: PASS
```

## 11. RC4：ChatGPT CONDITIONAL REJECT RC3 与 RC4 修复验证（2026-11-19 22:31–22:34）

- 背景：ChatGPT 独立审核 RC3（2026-11-19 22:31–22:32，1591 字）：CONDITIONAL REJECT。通过：ZIP 完整性（SHA-256 `1a97fdfb…` 与 Dash 公布的哈希一致）、Windows Host EXE 已打包、host 清单指向 .exe、扩展加了 tabs 权限、安装器可自动生成配置；88 项测试在 Dash 本地全部通过，ChatGPT 自己重跑时超时，未能复现全部结果（Dash 本地重跑：88 项，14.9 秒，全通过——很可能是 ChatGPT 一侧的环境时限）。两项必修：P0——Muse 审批收据仍可伪造（platform_receipt() 接受调用者提供的 approval_request_id 与 decided_by，_verify_credential() 只验字段不验真伪，代码自己承认了这一点）；P1——Native Host 实际在 Windows 上启动尚未验证。ChatGPT 随后批准 RC4 修复计划（22:32，1252 字）：直接开建，不用再讨论架构，不交给 Codex；附 3 条最终验收条件。
- P0 修复（审批卡作为执行授权来源已主动禁用）：`platform_receipt()` 调用即拒绝（`platform_receipt_disabled`）；`_verify_credential()` 拒绝任何 muse_approval_card 凭证；TRUSTED_CHANNELS 与 EXECUTION_CHANNELS 只剩 `("local_approval_page",)`；`check_execution()` 执行时重新核对整条批准记录，并拒绝 RC3 时代的平台通道批准；新增 `revoke()`；审计日志脱敏（token、session_token、pin、page_nonce、credential、receipt 一律写 [redacted]）。Muse 审批卡在 RC4 里只是通知/展示通道，直到平台能提供可验证的批准结果之前都保持禁用。手机推送测试的意义随之改变：只验证“通知能不能到达 Leo”，不再验证“卡上点的批准能不能授权执行”。
- 条件 1 修复（本地审批页身份验证加固）：PIN 防暴力破解（连续错 5 次锁定 15 分钟，锁定状态落盘、重启后仍在，锁定事件写审计日志，锁定期间对的 PIN 也拒绝）；会话令牌已用 secrets 模块生成（`secrets.token_urlsafe(32)`），绑定会话与审批人，单次使用、10 分钟过期；PIN 只在可信本地审批页表单里输入，没有任何代码路径接受从聊天消息、文本输入或命令行传来的 PIN 做验证（测试用静态扫描覆盖）；执行入口 `check_execution()` 在执行时重新验证授权，不信任 UI 显示的状态。执行模式默认仍禁用。
- 条件 2 修复（Windows 真机测试计划与脚本）：新增 `windows_e2e_test/`（`native_host_driver.py` 协议驱动、`run_e2e_test.bat` Windows 驱动、README 计划、`record-template.md` 记录模板）。隔离设计：独立 Chrome profile、测试专用注册表项 `com.agentrelay.host.e2e`、临时安装目录；.exe 找不到就拒绝，绝不回退 .bat/.py。Linux 上对 Python host 的预检：8 步全 PASS——这只是驱动脚本本身的逻辑预检，**不是 Windows 通过**。Windows E2E 仍为 PENDING。
- 条件 3 修复（GATE-AUTONOMY 独立验收）：`docs/GATES-v1.md` 与 `tests/acceptance_gates.md` 单独写明验收标准（Leo 只发起一次；Muse 与真实 ChatGPT 连续三轮实质讨论；Leo 不手动转发/复制粘贴/提示；消息、时间戳、轮次、结论全程可追溯；结束后自动生成供 Leo 决策的结论）；安装/安全测试不能代替这项验收。GATE-AUTONOMY 仍为 PENDING。
- 测试分批：`tests/run_tests.py` 支持 `--batch 1/2/3` 与 `--list-batches`（batch 1 = file_log、watchdog、locking、relay_client；batch 2 = approvals、local_page、run；batch 3 = native_host、extension_syntax、install）；每批先做 py_compile，原始输出存 `tests/test-output-rc4-batch-N.txt`，全量跑存 `tests/test-output-rc4.txt`。
- 自动化测试结果（2026-11-19，Dash 本地重跑）：batch 1：23 项，0 失败，0 错误，0 跳过，SUITE: PASS（5.5 秒）；batch 2：50 项，0 失败，0 错误，0 跳过，SUITE: PASS（10.5 秒）；batch 3：26 项，0 失败，0 错误，0 跳过，SUITE: PASS（3.4 秒）；全量：99 项，0 失败，0 错误，0 跳过，SUITE: PASS（19.3 秒）。
- 其他验证（2026-11-19，Dash 本地）：24 个 Python 文件 `py_compile` 全过；`manifest.json` 合法 JSON；`content.js` 与 `background.js` 经 `node --check` 语法通过；密钥扫描干净（只有测试用的 `test-token-123` 与扩展公开 key——公开 key 是固定扩展 ID 所需，设计如此；无 .pem/私钥文件；无 `<all_urls>`，只有两处注释写着“绝不是 `<all_urls>`”）；`.bat` 延迟展开走查通过（install.bat、uninstall.bat、run_e2e_test.bat、build_host_exe.bat 全程 `setlocal EnableDelayedExpansion` + `!VAR!`）。
- 诚实标注不变：GATE-HITL 为 PENDING（手机推送测试：Test 1 批准已通过，Test 2 拒绝与 Test 3 超时待验证）；Windows E2E 为 PENDING；GATE-AUTONOMY 为 PENDING；Muse handoff 自动唤醒为 NOT YET IMPLEMENTED；扩展未在真实 Chrome 加载测试；install/uninstall 未在真实 Windows 实测；agent-relay-host.exe 未在真实 Windows 运行过（见 docs/KNOWN-LIMITATIONS.md）。

### 11.1 Batch 1 原始输出（`tests/test-output-rc4-batch-1.txt`）

```
Agent Relay Skill v1.0.0-rc4 — automated test suite
============================================================
Scope: batch 1 (test_file_log, test_watchdog, test_locking, test_relay_client)

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
test_flaky_health_retries (test_relay_client.TestRelayClient.test_flaky_health_retries) ... ok
test_full_sequence (test_relay_client.TestRelayClient.test_full_sequence) ... ok
test_missing_token_clean_error (test_relay_client.TestRelayClient.test_missing_token_clean_error) ... ok

----------------------------------------------------------------------
Ran 23 tests in 5.464s

OK

Tests run: 23, failures: 0, errors: 0, skipped: 0
SUITE: PASS
```

### 11.2 Batch 2 原始输出（`tests/test-output-rc4-batch-2.txt`）

```
Agent Relay Skill v1.0.0-rc4 — automated test suite
============================================================
Scope: batch 2 (test_approvals, test_local_page, test_run)

[1/2] py_compile all Python files in the package
py_compile: PASS

[2/2] unittest suite
test_approve_once_then_execution_allowed (test_approvals.TestApprovals.test_approve_once_then_execution_allowed) ... ok
test_approver_mismatch_denied (test_approvals.TestApprovals.test_approver_mismatch_denied) ... ok
test_caller_declared_channel_string_denied (test_approvals.TestApprovals.test_caller_declared_channel_string_denied) ... ok
test_execution_refuses_rc3_platform_approval (test_approvals.TestApprovals.test_execution_refuses_rc3_platform_approval) ... ok
test_execution_refuses_unceremonied_approval (test_approvals.TestApprovals.test_execution_refuses_unceremonied_approval) ... ok
test_execution_reverifies_approved_option (test_approvals.TestApprovals.test_execution_reverifies_approved_option) ... ok
test_execution_reverifies_expired_approval (test_approvals.TestApprovals.test_execution_reverifies_expired_approval) ... ok
test_expire_overdue (test_approvals.TestApprovals.test_expire_overdue) ... ok
test_expired_token_denied (test_approvals.TestApprovals.test_expired_token_denied) ... ok
test_hand_built_platform_receipt_denied (test_approvals.TestApprovals.test_hand_built_platform_receipt_denied) ... ok
test_local_page_credential_allowed (test_approvals.TestApprovals.test_local_page_credential_allowed) ... ok
test_no_approval_denied (test_approvals.TestApprovals.test_no_approval_denied) ... ok
test_operation_id_mismatch_denied (test_approvals.TestApprovals.test_operation_id_mismatch_denied) ... ok
test_page_session_expired_denied (test_approvals.TestApprovals.test_page_session_expired_denied) ... ok
test_page_session_single_use (test_approvals.TestApprovals.test_page_session_single_use) ... ok
test_page_session_unknown_token_denied (test_approvals.TestApprovals.test_page_session_unknown_token_denied) ... ok
test_page_session_wrong_nonce_denied (test_approvals.TestApprovals.test_page_session_wrong_nonce_denied) ... ok
test_params_digest_mismatch_denied (test_approvals.TestApprovals.test_params_digest_mismatch_denied) ... ok
test_platform_receipt_factory_disabled (test_approvals.TestApprovals.test_platform_receipt_factory_disabled) ... ok
test_reject_flow_blocks_execution (test_approvals.TestApprovals.test_reject_flow_blocks_execution) ... ok
test_replay_approve_denied_and_counted (test_approvals.TestApprovals.test_replay_approve_denied_and_counted) ... ok
test_revoke_blocks_execution (test_approvals.TestApprovals.test_revoke_blocks_execution) ... ok
test_second_execution_denied (test_approvals.TestApprovals.test_second_execution_denied) ... ok
test_session_decided_by_mismatch_denied (test_approvals.TestApprovals.test_session_decided_by_mismatch_denied) ... ok
test_status_hides_token_hash_and_nonce (test_approvals.TestApprovals.test_status_hides_token_hash_and_nonce) ... ok
test_token_never_stored_in_plain (test_approvals.TestApprovals.test_token_never_stored_in_plain) ... ok
test_tokens_never_in_logs (test_approvals.TestApprovals.test_tokens_never_in_logs) ... ok
test_wrong_option_denied (test_approvals.TestApprovals.test_wrong_option_denied) ... ok
test_wrong_token_denied (test_approvals.TestApprovals.test_wrong_token_denied) ... ok
test_approve_without_session_denied (test_local_page.TestLocalPage.test_approve_without_session_denied) ... ok
test_expired_session_token_refused (test_local_page.TestLocalPage.test_expired_session_token_refused) ... ok
test_full_flow_approve_then_gate_allows (test_local_page.TestLocalPage.test_full_flow_approve_then_gate_allows) ... ok
test_pin_file_stores_only_hash (test_local_page.TestLocalPage.test_pin_file_stores_only_hash) ... ok
test_pin_only_in_trusted_ui (test_local_page.TestLocalPage.test_pin_only_in_trusted_ui) ... ok
test_reject_flow (test_local_page.TestLocalPage.test_reject_flow) ... ok
test_session_single_use (test_local_page.TestLocalPage.test_session_single_use) ... ok
test_tokens_absent_from_store_after_flow (test_local_page.TestLocalPage.test_tokens_absent_from_store_after_flow) ... ok
test_wrong_nonce_denied (test_local_page.TestLocalPage.test_wrong_nonce_denied) ... ok
test_wrong_pin_lockout (test_local_page.TestLocalPage.test_wrong_pin_lockout) ... ok
test_wrong_pin_no_session (test_local_page.TestLocalPage.test_wrong_pin_no_session) ... ok
test_wrong_token_denied (test_local_page.TestLocalPage.test_wrong_token_denied) ... ok
test_create_advance_record_status (test_run.TestRunPy.test_create_advance_record_status) ... ok
test_reconcile_with_uncertain_pauses (test_run.TestRunPy.test_reconcile_with_uncertain_pauses) ... ok
test_unknown_project (test_run.TestRunPy.test_unknown_project) ... ok
test_execute_allowed_with_approval_writes_file (test_run.TestTwoModes.test_execute_allowed_with_approval_writes_file) ... ok
test_execute_non_whitelisted_action_refused (test_run.TestTwoModes.test_execute_non_whitelisted_action_refused) ... ok
test_execute_path_escape_refused (test_run.TestTwoModes.test_execute_path_escape_refused) ... ok
test_execute_refused_in_discussion_mode (test_run.TestTwoModes.test_execute_refused_in_discussion_mode) ... ok
test_execute_refused_without_approval (test_run.TestTwoModes.test_execute_refused_without_approval) ... ok
test_status_reports_mode_and_exe (test_run.TestTwoModes.test_status_reports_mode_and_exe) ... ok

----------------------------------------------------------------------
Ran 50 tests in 10.509s

OK

Tests run: 50, failures: 0, errors: 0, skipped: 0
SUITE: PASS
```

### 11.3 Batch 3 原始输出（`tests/test-output-rc4-batch-3.txt`）

```
Agent Relay Skill v1.0.0-rc4 — automated test suite
============================================================
Scope: batch 3 (test_native_host, test_extension_syntax, test_install)

[1/2] py_compile all Python files in the package
py_compile: PASS

[2/2] unittest suite
test_bad_auth_refused (test_native_host.TestNativeHost.test_bad_auth_refused) ... ok
test_coordinator_to_extension_forward (test_native_host.TestNativeHost.test_coordinator_to_extension_forward) ... ok
test_extension_to_coordinator_recorded (test_native_host.TestNativeHost.test_extension_to_coordinator_recorded) ... ok
test_host_exits_on_stdin_close (test_native_host.TestNativeHost.test_host_exits_on_stdin_close) ... ok
test_ping_round_trip (test_native_host.TestNativeHost.test_ping_round_trip) ... ok
test_secret_file_mode_0600 (test_native_host.TestNativeHost.test_secret_file_mode_0600) ... ok
test_fixed_extension_id_matches_key (test_extension_syntax.TestExtension.test_fixed_extension_id_matches_key)
The manifest carries a fixed public key; Chrome derives the ... ok
test_js_syntax_with_node (test_extension_syntax.TestExtension.test_js_syntax_with_node) ... ok
test_manifest_valid_and_minimal (test_extension_syntax.TestExtension.test_manifest_valid_and_minimal) ... ok
test_native_host_manifest_template (test_extension_syntax.TestExtension.test_native_host_manifest_template) ... ok
test_no_forbidden_capabilities (test_extension_syntax.TestExtension.test_no_forbidden_capabilities) ... ok
test_check_only (test_install.TestInstall.test_check_only) ... ok
test_happy_path (test_install.TestInstall.test_happy_path) ... ok
test_refuses_registry_conflict_non_interactive (test_install.TestInstall.test_refuses_registry_conflict_non_interactive) ... ok
test_refuses_when_dest_exists (test_install.TestInstall.test_refuses_when_dest_exists) ... ok
test_refuses_when_exe_missing (test_install.TestInstall.test_refuses_when_exe_missing) ... ok
test_registry_conflict_user_confirms_records_prior (test_install.TestInstall.test_registry_conflict_user_confirms_records_prior) ... ok
test_registry_conflict_user_says_no (test_install.TestInstall.test_registry_conflict_user_says_no) ... ok
test_rollback_on_failure (test_install.TestInstall.test_rollback_on_failure) ... ok
test_happy_path (test_install.TestUninstall.test_happy_path) ... ok
test_keep_state_backs_up (test_install.TestUninstall.test_keep_state_backs_up) ... ok
test_keep_state_backup_failure_refuses (test_install.TestUninstall.test_keep_state_backup_failure_refuses) ... ok
test_leaves_registry_alone_if_changed (test_install.TestUninstall.test_leaves_registry_alone_if_changed) ... ok
test_refuses_non_skill_target (test_install.TestUninstall.test_refuses_non_skill_target) ... ok
test_refuses_without_manifest (test_install.TestUninstall.test_refuses_without_manifest) ... ok
test_restores_prior_registry_value (test_install.TestUninstall.test_restores_prior_registry_value) ... ok

----------------------------------------------------------------------
Ran 26 tests in 3.407s

OK

Tests run: 26, failures: 0, errors: 0, skipped: 0
SUITE: PASS
```

### 11.4 全量原始输出（`tests/test-output-rc4.txt`，末尾汇总）

```

----------------------------------------------------------------------
Ran 99 tests in 19.258s

OK

Tests run: 99, failures: 0, errors: 0, skipped: 0
SUITE: PASS
```

## 12. RC4 修正版交付：ChatGPT 审核第一份 RC4 的结论与发布前检查（2026-11-19 23:24–）

- 背景：ChatGPT 独立审核第一份 RC4 ZIP（2026-11-19 23:24，1357 字）：CONDITIONAL REJECT。审批修复全部通过——Muse 审批收据禁用 PASS、`platform_receipt()` 调用被拒 PASS、执行门只认本地审批通道 PASS、PIN 失败上限已实现、会话令牌/过期/单次使用已实现；它自己独立重跑 Batch 1 通过 23/23（Batch 2–3 尚未独立复现）。唯一 P0 是它收到的文件有问题：它说收到的 ZIP 里缺 `transport/agent-relay-host.exe`（它的 .sha256、.c 源码与 build_host_exe.bat 都在），而 install.py 要求有这个 .exe 否则拒绝安装。
- 核对结果（Dash，2026-11-19）：实际交付的 ZIP 里 .exe 在——224,515 字节，`unzip -l` 可见，SHA-256 `0e6a9748685d48e435a7f07775bdb9ba020f1348661a154b9276e3bc37bf36de` 与 `transport/agent-relay-host.exe.sha256` 一致。ChatGPT 算出的 ZIP 哈希是 `02dcf688e66d7a2880a61abb9ede9a47913d378889f26b1f28785e9d40009ce2`，与 Dash 公布的 `5beff15246e9a90fc8d137d5cf7482160f2767ba12cf765e4edf401f46cbcb3b` 不同——它收到的不是 Dash 交付的文件。最可能的原因是下载/重新上传时 .exe 被剥掉了（杀毒软件隔离 ZIP 里的 .exe 是首要嫌疑），或者传错了文件。ChatGPT 的要求：(1) 补齐缺失的 .exe；(2) 保证 .exe 的 SHA-256 与校验文件一致；(3) 加一道发布前检查——任何安装必需文件缺失就阻止发布 ZIP；(4) 重新打包为修正版 RC4，这只是打包问题，不升架构、不进 RC5/RC6 迭代循环；(5) 然后进入 Windows 真机验证（Chrome Native Messaging 往返 + 安装/卸载）。另注：本地审批服务器与批准存储在同一台机器上，代码能验证令牌/会话，但本身挡不住已经拿到本机文件访问或进程控制权的攻击者——执行模式在 Windows E2E 安全验收通过前保持默认禁用。
- 修正内容（除检查脚本、它的测试与相关文档外，内容与第一份 RC4 完全相同；`diff -r` 对照第一份 RC4 树，除 `__pycache__` 外无差异；版本号仍为 1.0.0-rc4，不是 RC5；新 ZIP 在 `skill-v1-rc4-fixed/` 目录下，文件名仍为 `agent-relay-skill-v1.0.0-rc4.zip`）：
  - 新增 `tests/check_package.py`（标准库 only）：核对包目录里 20 个安装必需文件都在；核对 .exe 的 SHA-256 与 `transport/agent-relay-host.exe.sha256` 一致；给它一个 ZIP 路径时，同样核对 ZIP 内部这 20 个文件都在、且 ZIP 里的 .exe 哈希一致。任何一项不对就大声失败（非零退出 + 明确报错）。用法：`python3 tests/check_package.py`（查包目录）、`python3 tests/check_package.py <zip>`（查 ZIP）、`python3 tests/check_package.py --dir <dir> --zip <zip>`（两边都查）。
  - 发布流程改为硬性门槛：ZIP 只有在 `check_package.py` 对包目录和最终 ZIP 都通过之后才能发布；不通过不许发。
  - 新增 `tests/test_check_package.py`（已并入 batch 3）：完整包通过、缺文件失败、缺 .exe 失败、.exe 哈希不对失败、ZIP 内缺 .exe / 哈希不对失败、命令行端到端通过与失败，共 11 项。
  - 文档：`docs/CHANGELOG.md` 新增“修正版交付”条目；本文件新增本节；`docs/KNOWN-LIMITATIONS.md` 补修正版交付说明与上传提醒（直接传 ZIP 文件本身，不要解压再重打；.exe 再消失请查杀毒软件隔离区；上传后请把 ChatGPT 算出的 SHA-256 发回来核对）。
- 自动化测试结果（2026-11-19，Dash 本地重跑，修正版）：batch 1：23 项，0 失败，0 错误，0 跳过，SUITE: PASS（5.5 秒）；batch 2：50 项，0 失败，0 错误，0 跳过，SUITE: PASS（10.6 秒）；batch 3：37 项（原 26 项 + 检查脚本 11 项），0 失败，0 错误，0 跳过，SUITE: PASS（3.5 秒）；全量：110 项，0 失败，0 错误，0 跳过，SUITE: PASS（19.5 秒）。
- 补充修复（Dash 独立复核时发现）：第一次全量重跑时 `test_tokens_absent_from_store_after_flow` 失败 1 项——不是密钥泄漏，是测试本身的假阳性：断言用原始子串搜索在整个 store 文件里找 6 位 PIN，而 ISO 时间戳的 6 位微秒字段恰好撞上了随机 PIN（`"...32.228532+00:00"`）。store 里只有哈希（token_hash、session_token_hash、PIN 的盐哈希），没有原始密钥。修复：`tests/test_local_page.py` 里两处 PIN 断言改为按 JSON 值精确比对（store 用递归遍历全部字符串值；pin 文件核对键集合与值），两个长令牌仍保留子串检查（43 位随机串不会误报）。修复后全量连跑 3 次均为 110 项 0 失败，SUITE: PASS；batch 2 单独重跑 50 项 0 失败。测试输出文件已随修复重新生成。
- 诚实标注不变：GATE-HITL 为 PENDING；Windows E2E 为 PENDING；GATE-AUTONOMY 为 PENDING；Muse handoff 自动唤醒为 NOT YET IMPLEMENTED；扩展未在真实 Chrome 加载测试；install/uninstall 未在真实 Windows 实测；agent-relay-host.exe 未在真实 Windows 运行过（见 docs/KNOWN-LIMITATIONS.md）。

### 12.1 Batch 3 原始输出（`tests/test-output-rc4-batch-3.txt`，含新增的 11 项检查测试）

```
Agent Relay Skill v1.0.0-rc4 — automated test suite
============================================================
Scope: batch 3 (test_native_host, test_extension_syntax, test_install, test_check_package)

[1/2] py_compile all Python files in the package
py_compile: PASS

[2/2] unittest suite
test_bad_auth_refused (test_native_host.TestNativeHost.test_bad_auth_refused) ... ok
test_coordinator_to_extension_forward (test_native_host.TestNativeHost.test_coordinator_to_extension_forward) ... ok
test_extension_to_coordinator_recorded (test_native_host.TestNativeHost.test_extension_to_coordinator_recorded) ... ok
test_host_exits_on_stdin_close (test_native_host.TestNativeHost.test_host_exits_on_stdin_close) ... ok
test_ping_round_trip (test_native_host.TestNativeHost.test_ping_round_trip) ... ok
test_secret_file_mode_0600 (test_native_host.TestNativeHost.test_secret_file_mode_0600) ... ok
test_fixed_extension_id_matches_key (test_extension_syntax.TestExtension.test_fixed_extension_id_matches_key)
The manifest carries a fixed public key; Chrome derives the ... ok
test_js_syntax_with_node (test_extension_syntax.TestExtension.test_js_syntax_with_node) ... ok
test_manifest_valid_and_minimal (test_extension_syntax.TestExtension.test_manifest_valid_and_minimal) ... ok
test_native_host_manifest_template (test_extension_syntax.TestExtension.test_native_host_manifest_template) ... ok
test_no_forbidden_capabilities (test_extension_syntax.TestExtension.test_no_forbidden_capabilities) ... ok
test_check_only (test_install.TestInstall.test_check_only) ... ok
test_happy_path (test_install.TestInstall.test_happy_path) ... ok
test_refuses_registry_conflict_non_interactive (test_install.TestInstall.test_refuses_registry_conflict_non_interactive) ... ok
test_refuses_when_dest_exists (test_install.TestInstall.test_refuses_when_dest_exists) ... ok
test_refuses_when_exe_missing (test_install.TestInstall.test_refuses_when_exe_missing) ... ok
test_registry_conflict_user_confirms_records_prior (test_install.TestInstall.test_registry_conflict_user_confirms_records_prior) ... ok
test_registry_conflict_user_says_no (test_install.TestInstall.test_registry_conflict_user_says_no) ... ok
test_rollback_on_failure (test_install.TestInstall.test_rollback_on_failure) ... ok
test_happy_path (test_install.TestUninstall.test_happy_path) ... ok
test_keep_state_backs_up (test_install.TestUninstall.test_keep_state_backs_up) ... ok
test_keep_state_backup_failure_refuses (test_install.TestUninstall.test_keep_state_backup_failure_refuses) ... ok
test_leaves_registry_alone_if_changed (test_install.TestUninstall.test_leaves_registry_alone_if_changed) ... ok
test_refuses_non_skill_target (test_install.TestUninstall.test_refuses_non_skill_target) ... ok
test_refuses_without_manifest (test_install.TestUninstall.test_refuses_without_manifest) ... ok
test_restores_prior_registry_value (test_install.TestUninstall.test_restores_prior_registry_value) ... ok
test_cli_fails_loudly_on_incomplete_package (test_check_package.TestCheckPackage.test_cli_fails_loudly_on_incomplete_package) ... ok
test_cli_passes_on_real_package (test_check_package.TestCheckPackage.test_cli_passes_on_real_package) ... ok
test_cli_zip_argument (test_check_package.TestCheckPackage.test_cli_zip_argument) ... ok
test_complete_fake_tree_passes (test_check_package.TestCheckPackage.test_complete_fake_tree_passes) ... ok
test_exe_hash_mismatch_fails (test_check_package.TestCheckPackage.test_exe_hash_mismatch_fails)
EXE content differs from what the checksum file says — ... ok
test_missing_exe_fails (test_check_package.TestCheckPackage.test_missing_exe_fails) ... ok
test_missing_file_fails (test_check_package.TestCheckPackage.test_missing_file_fails) ... ok
test_real_package_dir_passes (test_check_package.TestCheckPackage.test_real_package_dir_passes)
The actual RC4 package directory must pass the check — ... ok
test_zip_exe_hash_mismatch_fails (test_check_package.TestCheckPackage.test_zip_exe_hash_mismatch_fails) ... ok
test_zip_missing_exe_fails (test_check_package.TestCheckPackage.test_zip_missing_exe_fails) ... ok
test_zip_passes (test_check_package.TestCheckPackage.test_zip_passes) ... ok

----------------------------------------------------------------------
Ran 37 tests in 3.459s

OK

Tests run: 37, failures: 0, errors: 0, skipped: 0
SUITE: PASS
```

### 12.2 全量原始输出（`tests/test-output-rc4.txt`，末尾汇总）

```

----------------------------------------------------------------------
Ran 110 tests in 19.528s

OK

Tests run: 110, failures: 0, errors: 0, skipped: 0
SUITE: PASS
```

## 13. RC4-hotfix：ChatGPT 审核修正版 RC4 的结论与 4 项修复验证（2026-11-19 23:54–）

- 背景：ChatGPT 独立审核修正版 RC4（2026-11-19 23:54，1892 字）：CONDITIONAL REJECT。审批修复全部通过——Muse 审批收据禁用 PASS、平台收据伪造已堵 PASS；EXE 打包修复通过——77 个文件、无损坏、EXE 在、PE 头合法、EXE SHA-256 `0e6a9748…` 与校验文件一致；扩展固定 ID 与公开 key 匹配 PASS；110 项测试它自己独立复现全部通过（batch 1：23/23、batch 2：50/50、batch 3：37/37）。4 个必修问题，Dash 逐项对照代码确认属实：P0——ping / health / read_latest 的回复不带 response nonce（只有 send 回显），`background.js` 原样转发回复，`adapter.py` 的 `_wait_outbox()` 按 nonce 匹配，于是浏览器明明回复了、适配器却超时；P0——`run.py` 的 `_project()` 只读创建记录（永远 CREATED），从不读 `_set_status()` 写的 `project_status` 记录，pause / complete 不生效，advance 的 COMPLETED / BLOCKED 拦截也永远触发不了；P1——`background.js` 的 HOST_NAME 是 `com.agentrelay.host`，E2E 脚本却注册 `com.agentrelay.host.e2e`，扩展永远连不上测试 host；P1——`doSend()` 点完发送按钮就立刻返回 ok:true，没确认消息真的进了对话。另：E2E 脚本手工复制文件、直接写注册表，没有真正跑 install.py / uninstall.py。ChatGPT 随后批准 hotfix 计划（23:57，1258 字）：四个修复方向全同意，立即开建，不用再确认，不升 RC5；附 3 条实现细节：(1) send_result 区分 MESSAGE_SENT 与 RESPONSE_COMPLETED——ok=true 只表示新用户消息已确认进对话历史，绝不表示 AI 回复已完成；确认不了返回 UNCERTAIN，绝不自动重发；异步等待保持扩展的消息回复通道打开；(2) 状态机强制执行状态限制——CREATED / DISCUSSING 允许 advance，PAUSED 拒绝（先 Resume），COMPLETED / BLOCKED 拒绝；读写不让旧事件覆盖新事件；重启恢复仍能识别终态；(3) Windows E2E 保持与日常环境隔离——优先用测试扩展 + `.e2e` Native Host，不覆盖正式 host 注册表项；测试扩展 ID 若变，清单的 allowed_origins 必须匹配；测试后只清理本次测试创建的东西。Hotfix 验收清单：ping / health / read_latest 完整 nonce 匹配；PAUSED / COMPLETED / BLOCKED 拦截 advance；测试扩展与测试 Native Host 正确配对；真正跑 install.py / uninstall.py；消息发送成功与 AI 回复完成分别确认；全部回归测试通过并附原始日志；ZIP / EXE / SHA-256 发布前检查通过。
- 修复内容（基线 = 修正版 RC4 树，复制到 `skill-v1-rc4-hotfix/`；版本号仍为 1.0.0-rc4，不升 RC5；新 ZIP 名 `agent-relay-skill-v1.0.0-rc4-hotfix.zip`）：
  - FIX 1（P0，nonce 回显）：`transport/extension/content.js`——ping 回 `{type:"pong", origin, nonce}`；`doHealth()` 与 `doReadLatest()` 的结果里带上请求 nonce；`background.js` 已原样转发回复（`sendToHost(resp)`），nonce 随之到达 outbox，无需改动。新增 `tests/test_adapter_nonce.py`（7 项）与 `tests/content_js_harness.js`（Node 桩环境，15 项断言）+ `tests/test_content_js.py`（1 项）。
  - FIX 2（P0，状态机读最新状态 + 强制状态限制）：`orchestrator/run.py`——`_project()` 合并最新一条 `project_status` 记录（latest-wins）；新增 `_is_terminal()`；advance 只允许 CREATED / DISCUSSING，PAUSED 拒绝并提示先 resume（错误 `project_paused`），COMPLETED / BLOCKED 拒绝（错误 `project_closed`）；通过对账后首次 advance / 从 PAUSED_UNCERTAIN 恢复时写 DISCUSSING 状态记录；resume 成功时写 DISCUSSING 状态记录；resume / pause / complete 在终态下拒绝。新增 `tests/test_run.py` 的 `TestStateMachine`（6 项）。
  - FIX 3（P1，Windows E2E host 配对 + 真跑安装/卸载）：`install.py` 接受 `--host-name`（默认 `com.agentrelay.host`；E2E 用 `com.agentrelay.host.e2e`），只允许 `com.agentrelay.host` 或 `com.agentrelay.host.*`；安装清单记录 `host_name` 与 `registry_key`；修复安装清单版本号写错（"1.0.0-rc3" → "1.0.0-rc4"）。`uninstall.py` 按安装清单里的 `registry_key` 删注册表项。新增 `windows_e2e_test/make_test_extension.py`。`windows_e2e_test/run_e2e_test.bat` 重写：跑真正的 install.py / uninstall.py，不再手工复制包、不再直接写注册表；Chrome 加载测试扩展；正式注册表项安装前/安装后/卸载后三次 `fc` 核对。`windows_e2e_test/README.md` 与 `record-template.md` 同步更新（新增安装/卸载核对表 I1–I4、U1–U4）。新增 `tests/test_e2e.py`（12 项）与 `tests/test_install.py` 的 `TestInstallTestHostName`（3 项）。
  - FIX 4（P1，send 确认区分 MESSAGE_SENT 与 RESPONSE_COMPLETED）：`transport/extension/content.js` 的 `doSend()` 改为异步：点发送后等待输入框清空 **且** 新用户消息出现在 DOM 里（最长 5 秒），确认后才返回 ok:true + `delivery:"message_sent"`；确认不了返回 ok:false + `delivery:"uncertain"` + 错误 `send_unconfirmed`，绝不自动重发；发送监听器返回 true，保持异步回复通道打开。`transport/adapter.py` 的 `send()` 返回 delivery 状态，`delivery:"uncertain"` 时即便 ok 也按不确定处理。文档：`transport/browser_adapter.md` 与 `transport/extension/README.md` 新增 send 语义说明。
  - 发布检查：`tests/check_package.py` 的必需文件清单从 20 个加到 24 个（新增 `windows_e2e_test/make_test_extension.py`、`tests/test_content_js.py`、`tests/test_adapter_nonce.py`、`tests/test_e2e.py`、`tests/content_js_harness.js`）；batch 3 新增 `test_adapter_nonce`、`test_content_js`、`test_e2e`。
- 自动化测试结果（2026-11-19，Dash 本地重跑，hotfix 版）：batch 1：23 项（file_log 13、watchdog 5、locking 2、relay_client 3），0 失败，0 错误，0 跳过，SUITE: PASS（5.5 秒）；batch 2：56 项（approvals 29、local_page 12、run 15，含新增的状态机 6 项），0 失败，0 错误，0 跳过，SUITE: PASS（13.0 秒）；batch 3：60 项（native_host 6、extension_syntax 5、install 18、check_package 11、adapter_nonce 7、content_js 1、e2e 12），0 失败，0 错误，0 跳过，SUITE: PASS（14.2 秒）；全量：139 项，0 失败，0 错误，0 跳过，SUITE: PASS（32.3 秒）。
- 诚实标注不变：GATE-HITL 为 PENDING；Windows E2E 为 PENDING（本机没有 Windows、没有 wine，run_e2e_test.bat 未在真实 Windows 跑过；install/uninstall 只在 Linux 单元测试里用 FakeRegistry 验证过）；GATE-AUTONOMY 为 PENDING；Muse handoff 自动唤醒为 NOT YET IMPLEMENTED；扩展未在真实 Chrome 加载测试；agent-relay-host.exe 未在真实 Windows 运行过（见 docs/KNOWN-LIMITATIONS.md）。

### 13.1 Batch 3 原始输出（`tests/test-output-rc4-hotfix-batch-3.txt`，含新增的 23 项 hotfix 测试）

```
Agent Relay Skill v1.0.0-rc4 — automated test suite
============================================================
Scope: batch 3 (test_native_host, test_extension_syntax, test_install, test_check_package, test_adapter_nonce, test_content_js, test_e2e)

[1/2] py_compile all Python files in the package
py_compile: PASS

[2/2] unittest suite
test_bad_auth_refused (test_native_host.TestNativeHost.test_bad_auth_refused) ... ok
test_coordinator_to_extension_forward (test_native_host.TestNativeHost.test_coordinator_to_extension_forward) ... ok
test_extension_to_coordinator_recorded (test_native_host.TestNativeHost.test_extension_to_coordinator_recorded) ... ok
test_host_exits_on_stdin_close (test_native_host.TestNativeHost.test_host_exits_on_stdin_close) ... ok
test_ping_round_trip (test_native_host.TestNativeHost.test_ping_round_trip) ... ok
test_secret_file_mode_0600 (test_native_host.TestNativeHost.test_secret_file_mode_0600) ... ok
test_fixed_extension_id_matches_key (test_extension_syntax.TestExtension.test_fixed_extension_id_matches_key)
The manifest carries a fixed public key; Chrome derives the ... ok
test_js_syntax_with_node (test_extension_syntax.TestExtension.test_js_syntax_with_node) ... ok
test_manifest_valid_and_minimal (test_extension_syntax.TestExtension.test_manifest_valid_and_minimal) ... ok
test_native_host_manifest_template (test_extension_syntax.TestExtension.test_native_host_manifest_template) ... ok
test_no_forbidden_capabilities (test_extension_syntax.TestExtension.test_no_forbidden_capabilities) ... ok
test_check_only (test_install.TestInstall.test_check_only) ... ok
test_happy_path (test_install.TestInstall.test_happy_path) ... ok
test_refuses_registry_conflict_non_interactive (test_install.TestInstall.test_refuses_registry_conflict_non_interactive) ... ok
test_refuses_when_dest_exists (test_install.TestInstall.test_refuses_when_dest_exists) ... ok
test_refuses_when_exe_missing (test_install.TestInstall.test_refuses_when_exe_missing) ... ok
test_registry_conflict_user_confirms_records_prior (test_install.TestInstall.test_registry_conflict_user_confirms_records_prior) ... ok
test_registry_conflict_user_says_no (test_install.TestInstall.test_registry_conflict_user_says_no) ... ok
test_rollback_on_failure (test_install.TestInstall.test_rollback_on_failure) ... ok
test_bad_host_name_refused (test_install.TestInstallTestHostName.test_bad_host_name_refused) ... ok
test_custom_host_name_writes_only_test_key (test_install.TestInstallTestHostName.test_custom_host_name_writes_only_test_key) ... ok
test_uninstall_removes_test_key_not_production (test_install.TestInstallTestHostName.test_uninstall_removes_test_key_not_production) ... ok
test_happy_path (test_install.TestUninstall.test_happy_path) ... ok
test_keep_state_backs_up (test_install.TestUninstall.test_keep_state_backs_up) ... ok
test_keep_state_backup_failure_refuses (test_install.TestUninstall.test_keep_state_backup_failure_refuses) ... ok
test_leaves_registry_alone_if_changed (test_install.TestUninstall.test_leaves_registry_alone_if_changed) ... ok
test_refuses_non_skill_target (test_install.TestUninstall.test_refuses_non_skill_target) ... ok
test_refuses_without_manifest (test_install.TestUninstall.test_refuses_without_manifest) ... ok
test_restores_prior_registry_value (test_install.TestUninstall.test_restores_prior_registry_value) ... ok
test_cli_fails_loudly_on_incomplete_package (test_check_package.TestCheckPackage.test_cli_fails_loudly_on_incomplete_package) ... ok
test_cli_passes_on_real_package (test_check_package.TestCheckPackage.test_cli_passes_on_real_package) ... ok
test_cli_zip_argument (test_check_package.TestCheckPackage.test_cli_zip_argument) ... ok
test_complete_fake_tree_passes (test_check_package.TestCheckPackage.test_complete_fake_tree_passes) ... ok
test_exe_hash_mismatch_fails (test_check_package.TestCheckPackage.test_exe_hash_mismatch_fails)
EXE content differs from what the checksum file says — ... ok
test_missing_exe_fails (test_check_package.TestCheckPackage.test_missing_exe_fails) ... ok
test_missing_file_fails (test_check_package.TestCheckPackage.test_missing_file_fails) ... ok
test_real_package_dir_passes (test_check_package.TestCheckPackage.test_real_package_dir_passes)
The actual RC4 package directory must pass the check — ... ok
test_zip_exe_hash_mismatch_fails (test_check_package.TestCheckPackage.test_zip_exe_hash_mismatch_fails) ... ok
test_zip_missing_exe_fails (test_check_package.TestCheckPackage.test_zip_missing_exe_fails) ... ok
test_zip_passes (test_check_package.TestCheckPackage.test_zip_passes) ... ok
test_health_echoes_nonce (test_adapter_nonce.TestAdapterNonce.test_health_echoes_nonce) ... ok
test_nonce_less_reply_never_matches (test_adapter_nonce.TestAdapterNonce.test_nonce_less_reply_never_matches) ... ok
test_ping_pong_nonce_matches (test_adapter_nonce.TestAdapterNonce.test_ping_pong_nonce_matches) ... ok
test_read_latest_echoes_nonce (test_adapter_nonce.TestAdapterNonce.test_read_latest_echoes_nonce) ... ok
test_send_confirmed_is_message_sent (test_adapter_nonce.TestAdapterNonce.test_send_confirmed_is_message_sent) ... ok
test_send_not_sent_is_failed (test_adapter_nonce.TestAdapterNonce.test_send_not_sent_is_failed) ... ok
test_send_unconfirmed_is_uncertain (test_adapter_nonce.TestAdapterNonce.test_send_unconfirmed_is_uncertain) ... ok
test_harness_all_checks_pass (test_content_js.TestContentJs.test_harness_all_checks_pass) ... ok
test_bat_builds_test_extension (test_e2e.TestE2EBatWiring.test_bat_builds_test_extension) ... ok
test_bat_does_not_copy_package_or_write_registry_directly (test_e2e.TestE2EBatWiring.test_bat_does_not_copy_package_or_write_registry_directly) ... ok
test_bat_loads_test_extension_not_production (test_e2e.TestE2EBatWiring.test_bat_loads_test_extension_not_production) ... ok
test_bat_runs_real_install (test_e2e.TestE2EBatWiring.test_bat_runs_real_install) ... ok
test_bat_runs_real_uninstall (test_e2e.TestE2EBatWiring.test_bat_runs_real_uninstall) ... ok
test_bat_verifies_production_key_unchanged (test_e2e.TestE2EBatWiring.test_bat_verifies_production_key_unchanged) ... ok
test_dest_rebuilt_on_repeat (test_e2e.TestMakeTestExtension.test_dest_rebuilt_on_repeat) ... ok
test_happy_path (test_e2e.TestMakeTestExtension.test_happy_path) ... ok
test_missing_host_name_declaration_fails_and_cleans_up (test_e2e.TestMakeTestExtension.test_missing_host_name_declaration_fails_and_cleans_up) ... ok
test_missing_source_refused (test_e2e.TestMakeTestExtension.test_missing_source_refused) ... ok
test_production_host_name_refused (test_e2e.TestMakeTestExtension.test_production_host_name_refused) ... ok
test_unrelated_host_name_refused (test_e2e.TestMakeTestExtension.test_unrelated_host_name_refused) ... ok

----------------------------------------------------------------------
Ran 60 tests in 14.181s

OK

Tests run: 60, failures: 0, errors: 0, skipped: 0
SUITE: PASS
```

### 13.2 全量原始输出（`tests/test-output-rc4-hotfix.txt`，末尾汇总）

```

----------------------------------------------------------------------
Ran 139 tests in 32.308s

OK

Tests run: 139, failures: 0, errors: 0, skipped: 0
SUITE: PASS
```

## 14. RC4-hotfix2：ChatGPT 审核第一份 hotfix 的结论与 3 项任务验证（2026-11-20）

- 背景：ChatGPT 独立审核第一份 hotfix（2026-11-20 10:13，约 1700 字）：原 hotfix 包按收到时的样子 REJECT——它收到的文件只有 85 项、没有 `transport/agent-relay-host.exe`；Dash 当场重新核对交付的文件：86 项，.exe 在里面（224,515 字节，SHA-256 `4129a0e0…` 与公布一致）。**.exe 在传输途中第二次被剥掉了**（第一次是原 RC4：它算出的 ZIP 哈希 `02dcf688…` 与 Dash 公布的 `5beff152…` 不同）。打包本身两次都没坏，问题在下载/重新上传的链路。ChatGPT 同时给它自己拼的审计包（从修正版 RC4 把 .exe 合并回来，SHA-256 `49058ac9…`——另一个文件，不是 Dash 的交付）判了有条件通过，可做集成准备，不是正式发布。它还指出 2 个新的可靠性问题（都是模拟 DOM 测试，未在真实 Chrome 复现，但逻辑漏洞经 Dash 对照代码确认属实），并给了 3 个直接任务，不升版本、不重新设计：(1) 修 read_latest() 把用户消息误认成 ChatGPT 回复；(2) 修 send 确认把旧文本误判为新发送；(3) 把 check_package.py 变成强制发布门（失败 = 不交付）。ChatGPT 明确：下一步优先在 Leo 的 Windows 隔离环境做真实集成，而不是继续加模拟测试。另：Edge / Firefox 自适应不在本次 hotfix 里，是以后的兼容性任务，不阻塞 Chrome 真实链路。Round 9 已发给 ChatGPT（2026-11-20 10:14）：接受结论，附 .exe 差异证据、两处问题的代码证据与三项任务的具体修法；下个交付命名为 agent-relay-skill-v1.0.0-rc4-hotfix2.zip（版本号仍为 1.0.0-rc4）。
- 修复内容（基线 = 第一份 hotfix 树，复制到 `skill-v1-rc4-hotfix2/`；版本号仍为 1.0.0-rc4，不升 RC5；新 ZIP 名 `agent-relay-skill-v1.0.0-rc4-hotfix2.zip`）：
  - TASK 1（read_latest 只认肯定确认的助手节点）：`transport/extension/content.js`——`REPLY_SELECTORS` 改为只有 `["[data-message-author-role='assistant']"]`，ChatGPT 与 Muse 两边都删掉通用的 "article" 兜底；没有肯定确认的助手节点时 `latestReply()` 返回 null，read_latest 报 found:false，completion watch 什么也不报，绝不猜。`tests/content_js_harness.js` 新增断言：用户 article 在助手回复之后出现时仍返回助手回复（含 dom_id 核对）；只有用户 article 时 found:false 且结果里没有任何 sender 标注；completion watch 只报助手回复、不报用户消息（MutationObserver 桩 + sendMessage 记录）。
  - TASK 2（send 确认先拍快照、要求新节点）：`transport/extension/content.js`——新增 `userMessageFingerprints()`（每个用户块的 dom_id + 文本）与 `findNewUserMessage()`（新节点 = 数量增加、或新的 dom_id、或新的内容指纹；dom_id 缺失时按位置判断）；`doSend()` 在 `send.click()` 之前拍快照，`waitForSendConfirmation()` 要求出现含发送内容的新节点才确认；确认后 send_result 带 `message_id`（新节点的 data-message-id，页面提供时）；只有旧的相同文本、没有新节点 → UNCERTAIN（ok:false、`delivery:"uncertain"`、错误 `send_unconfirmed`），绝不自动重发。`tests/content_js_harness.js` 新增断言：重复文本 + 真有新节点 → message_sent 且 message_id 是新 ID；重复文本 + 输入框清空但无新节点 → UNCERTAIN；新发送返回的 message_id 是新节点的 data-message-id；另加 "clear-only" 模拟模式（输入框清空、无新节点）。
  - TASK 3（发布门强制化 + 包内清单）：新增 `tests/release_gate.py`（标准库 only）：(1) 删掉目标 ZIP 旁已有的 .sha256；(2) 从包目录当前内容（重新）生成 `MANIFEST.json`；(3) 跑 `tests/check_package.py --dir`；(4) 从包目录建 ZIP（排序、去 `__pycache__` / `.pyc`）；(5) 跑 `tests/check_package.py --dir --zip`；(6) 全部通过才写 .sha256（写完再读一遍核对）。任何一步失败都非零退出，不写 .sha256，并删掉刚建的 ZIP。`MANIFEST.json` 在 ZIP 里面（68 个文件 + SHA-256 + file_count + total_bytes；故意不覆盖 MANIFEST.json 自己、`__pycache__` / `*.pyc`、`tests/test-output-*.txt`，清单本身写明排除原因）。`tests/check_package.py` 现在核对清单（包目录与 ZIP 里的清单必须与实际内容一致；同时给 `--dir` 与 `--zip` 时，ZIP 里的清单必须与包目录的清单逐字节一致）；必需文件清单从 24 个加到 26 个（新增 MANIFEST.json 与 tests/release_gate.py）。新增 `tests/test_release_gate.py`（6 项）与 `tests/test_check_package.py` 的清单测试（6 项）。测试分批：batch 3 新增 `test_release_gate`。文档：`docs/CHANGELOG.md`（hotfix2 条目）、`docs/KNOWN-LIMITATIONS.md`（hotfix2 节 + 接收方核对方法）、`docs/INSTALL.md`（第 7 节：强制发布流程）、`transport/browser_adapter.md` 第 3a 节与 `transport/extension/README.md`（发送语义 + 只认助手节点的读语义）。
- 自动化测试结果（2026-11-20，Dash 本地重跑，hotfix2 版）：batch 1：23 项（file_log 13、watchdog 5、locking 2、relay_client 3），0 失败，0 错误，0 跳过，SUITE: PASS（5.5 秒）；batch 2：56 项（approvals 29、local_page 12、run 15），0 失败，0 错误，0 跳过，SUITE: PASS（12.8 秒）；batch 3：72 项（native_host 6、extension_syntax 5、install 18、check_package 17、adapter_nonce 7、content_js 1、e2e 12、release_gate 6），0 失败，0 错误，0 跳过，SUITE: PASS（27.1 秒）；全量：151 项，0 失败，0 错误，0 跳过，SUITE: PASS（45.3 秒）。另做：`py_compile` 全部 Python 文件通过；`manifest.json` 合法 JSON；content.js 与 background.js 通过 `node --check`；密钥扫描干净（只有 localhost stub / 测试里的 test-token-123 与测试里的 "<redacted>" 占位）；ZIP 里无 `__pycache__` / `.pyc`；`diff -r` 对照第一份 hotfix 树只有预期的改动（MANIFEST.json、release_gate.py、test_release_gate.py、hotfix2 测试输出、改过的 12 个文件）。
- 发布门拒绝演示（2026-11-20，Dash 本地，/tmp 临时包）：故意去掉 .exe 的坏包 + 预先放一个过期的 .sha256（"deadbeef"）→ 发布门在第 3 步拒绝（check_package 报 "missing required file: transport/agent-relay-host.exe"），退出码 1；跑完后既没有 ZIP 也没有 .sha256（过期的 .sha256 已在第 1 步删掉）。好包上的发布门通过：ZIP 83 项，.sha256 写入并经重读核对（最终哈希以 ZIP 旁的 `agent-relay-skill-v1.0.0-rc4-hotfix2.zip.sha256` 文件为准；文档里不写死哈希，因为清单是发布时最后生成的，写死会过期）。
- 诚实标注不变：GATE-HITL 为 PENDING；Windows E2E 为 PENDING（本机没有 Windows、没有 wine，run_e2e_test.bat 未在真实 Windows 跑过；install/uninstall 只在 Linux 单元测试里用 FakeRegistry 验证过）；GATE-AUTONOMY 为 PENDING；Muse handoff 自动唤醒为 NOT YET IMPLEMENTED；扩展未在真实 Chrome 加载测试；agent-relay-host.exe 未在真实 Windows 运行过（见 docs/KNOWN-LIMITATIONS.md）。Node 桩（content_js_harness.js）证明的是 content.js 自己的逻辑路径（nonce 回显、只认助手节点、快照式发送确认、UNCERTAIN 路径），不是真实 Chrome 的 DOM 行为。

### 14.1 Batch 3 原始输出（`tests/test-output-rc4-hotfix2-batch-3.txt`，含新增的清单 6 项与发布门 6 项）

```
Agent Relay Skill v1.0.0-rc4 — automated test suite
============================================================
Scope: batch 3 (test_native_host, test_extension_syntax, test_install, test_check_package, test_adapter_nonce, test_content_js, test_e2e, test_release_gate)

[1/2] py_compile all Python files in the package
py_compile: PASS

[2/2] unittest suite
test_bad_auth_refused (test_native_host.TestNativeHost.test_bad_auth_refused) ... ok
test_coordinator_to_extension_forward (test_native_host.TestNativeHost.test_coordinator_to_extension_forward) ... ok
test_extension_to_coordinator_recorded (test_native_host.TestNativeHost.test_extension_to_coordinator_recorded) ... ok
test_host_exits_on_stdin_close (test_native_host.TestNativeHost.test_host_exits_on_stdin_close) ... ok
test_ping_round_trip (test_native_host.TestNativeHost.test_ping_round_trip) ... ok
test_secret_file_mode_0600 (test_native_host.TestNativeHost.test_secret_file_mode_0600) ... ok
test_fixed_extension_id_matches_key (test_extension_syntax.TestExtension.test_fixed_extension_id_matches_key)
The manifest carries a fixed public key; Chrome derives the ... ok
test_js_syntax_with_node (test_extension_syntax.TestExtension.test_js_syntax_with_node) ... ok
test_manifest_valid_and_minimal (test_extension_syntax.TestExtension.test_manifest_valid_and_minimal) ... ok
test_native_host_manifest_template (test_extension_syntax.TestExtension.test_native_host_manifest_template) ... ok
test_no_forbidden_capabilities (test_extension_syntax.TestExtension.test_no_forbidden_capabilities) ... ok
test_check_only (test_install.TestInstall.test_check_only) ... ok
test_happy_path (test_install.TestInstall.test_happy_path) ... ok
test_refuses_registry_conflict_non_interactive (test_install.TestInstall.test_refuses_registry_conflict_non_interactive) ... ok
test_refuses_when_dest_exists (test_install.TestInstall.test_refuses_when_dest_exists) ... ok
test_refuses_when_exe_missing (test_install.TestInstall.test_refuses_when_exe_missing) ... ok
test_registry_conflict_user_confirms_records_prior (test_install.TestInstall.test_registry_conflict_user_confirms_records_prior) ... ok
test_registry_conflict_user_says_no (test_install.TestInstall.test_registry_conflict_user_says_no) ... ok
test_rollback_on_failure (test_install.TestInstall.test_rollback_on_failure) ... ok
test_bad_host_name_refused (test_install.TestInstallTestHostName.test_bad_host_name_refused) ... ok
test_custom_host_name_writes_only_test_key (test_install.TestInstallTestHostName.test_custom_host_name_writes_only_test_key) ... ok
test_uninstall_removes_test_key_not_production (test_install.TestInstallTestHostName.test_uninstall_removes_test_key_not_production) ... ok
test_happy_path (test_install.TestUninstall.test_happy_path) ... ok
test_keep_state_backs_up (test_install.TestUninstall.test_keep_state_backs_up) ... ok
test_keep_state_backup_failure_refuses (test_install.TestUninstall.test_keep_state_backup_failure_refuses) ... ok
test_leaves_registry_alone_if_changed (test_install.TestUninstall.test_leaves_registry_alone_if_changed) ... ok
test_refuses_non_skill_target (test_install.TestUninstall.test_refuses_non_skill_target) ... ok
test_refuses_without_manifest (test_install.TestUninstall.test_refuses_without_manifest) ... ok
test_restores_prior_registry_value (test_install.TestUninstall.test_restores_prior_registry_value) ... ok
test_cli_fails_loudly_on_incomplete_package (test_check_package.TestCheckPackage.test_cli_fails_loudly_on_incomplete_package) ... ok
test_cli_passes_on_real_package (test_check_package.TestCheckPackage.test_cli_passes_on_real_package) ... ok
test_cli_zip_argument (test_check_package.TestCheckPackage.test_cli_zip_argument) ... ok
test_complete_fake_tree_passes (test_check_package.TestCheckPackage.test_complete_fake_tree_passes) ... ok
test_exe_hash_mismatch_fails (test_check_package.TestCheckPackage.test_exe_hash_mismatch_fails)
EXE content differs from what the checksum file says — ... ok
test_manifest_excludes_test_outputs (test_check_package.TestCheckPackage.test_manifest_excludes_test_outputs)
Volatile test-run outputs (tests/test-output-*.txt) are ... ok
test_manifest_missing_fails (test_check_package.TestCheckPackage.test_manifest_missing_fails)
No MANIFEST.json at all: the receiver cannot verify ... ok
test_manifest_stale_fails (test_check_package.TestCheckPackage.test_manifest_stale_fails)
A file changed after the manifest was generated: the ... ok
test_manifest_unlisted_file_fails (test_check_package.TestCheckPackage.test_manifest_unlisted_file_fails)
A file present in the package but not listed in the ... ok
test_missing_exe_fails (test_check_package.TestCheckPackage.test_missing_exe_fails) ... ok
test_missing_file_fails (test_check_package.TestCheckPackage.test_missing_file_fails) ... ok
test_real_package_dir_passes (test_check_package.TestCheckPackage.test_real_package_dir_passes)
The actual RC4 package directory must pass the check — ... ok
test_zip_exe_hash_mismatch_fails (test_check_package.TestCheckPackage.test_zip_exe_hash_mismatch_fails) ... ok
test_zip_manifest_mismatch_fails (test_check_package.TestCheckPackage.test_zip_manifest_mismatch_fails)
The manifest inside the ZIP does not match the ZIP's ... ok
test_zip_manifest_missing_fails (test_check_package.TestCheckPackage.test_zip_manifest_missing_fails)
ZIP without MANIFEST.json: the receiver cannot verify ... ok
test_zip_missing_exe_fails (test_check_package.TestCheckPackage.test_zip_missing_exe_fails) ... ok
test_zip_passes (test_check_package.TestCheckPackage.test_zip_passes) ... ok
test_health_echoes_nonce (test_adapter_nonce.TestAdapterNonce.test_health_echoes_nonce) ... ok
test_nonce_less_reply_never_matches (test_adapter_nonce.TestAdapterNonce.test_nonce_less_reply_never_matches) ... ok
test_ping_pong_nonce_matches (test_adapter_nonce.TestAdapterNonce.test_ping_pong_nonce_matches) ... ok
test_read_latest_echoes_nonce (test_adapter_nonce.TestAdapterNonce.test_read_latest_echoes_nonce) ... ok
test_send_confirmed_is_message_sent (test_adapter_nonce.TestAdapterNonce.test_send_confirmed_is_message_sent) ... ok
test_send_not_sent_is_failed (test_adapter_nonce.TestAdapterNonce.test_send_not_sent_is_failed) ... ok
test_send_unconfirmed_is_uncertain (test_adapter_nonce.TestAdapterNonce.test_send_unconfirmed_is_uncertain) ... ok
test_harness_all_checks_pass (test_content_js.TestContentJs.test_harness_all_checks_pass) ... ok
test_bat_builds_test_extension (test_e2e.TestE2EBatWiring.test_bat_builds_test_extension) ... ok
test_bat_does_not_copy_package_or_write_registry_directly (test_e2e.TestE2EBatWiring.test_bat_does_not_copy_package_or_write_registry_directly) ... ok
test_bat_loads_test_extension_not_production (test_e2e.TestE2EBatWiring.test_bat_loads_test_extension_not_production) ... ok
test_bat_runs_real_install (test_e2e.TestE2EBatWiring.test_bat_runs_real_install) ... ok
test_bat_runs_real_uninstall (test_e2e.TestE2EBatWiring.test_bat_runs_real_uninstall) ... ok
test_bat_verifies_production_key_unchanged (test_e2e.TestE2EBatWiring.test_bat_verifies_production_key_unchanged) ... ok
test_dest_rebuilt_on_repeat (test_e2e.TestMakeTestExtension.test_dest_rebuilt_on_repeat) ... ok
test_happy_path (test_e2e.TestMakeTestExtension.test_happy_path) ... ok
test_missing_host_name_declaration_fails_and_cleans_up (test_e2e.TestMakeTestExtension.test_missing_host_name_declaration_fails_and_cleans_up) ... ok
test_missing_source_refused (test_e2e.TestMakeTestExtension.test_missing_source_refused) ... ok
test_production_host_name_refused (test_e2e.TestMakeTestExtension.test_production_host_name_refused) ... ok
test_unrelated_host_name_refused (test_e2e.TestMakeTestExtension.test_unrelated_host_name_refused) ... ok
test_gate_cli (test_release_gate.TestReleaseGate.test_gate_cli) ... ok
test_gate_passes_and_writes_sha256 (test_release_gate.TestReleaseGate.test_gate_passes_and_writes_sha256) ... ok
test_gate_refuses_exe_hash_mismatch (test_release_gate.TestReleaseGate.test_gate_refuses_exe_hash_mismatch) ... ok
test_gate_refuses_missing_exe (test_release_gate.TestReleaseGate.test_gate_refuses_missing_exe)
The transit-strip case: the EXE is gone. The gate must ... ok
test_gate_removes_stale_sha256_on_failure (test_release_gate.TestReleaseGate.test_gate_removes_stale_sha256_on_failure)
A pre-existing .sha256 must not survive a failed run — ... ok
test_gate_writes_manifest_into_package_dir (test_release_gate.TestReleaseGate.test_gate_writes_manifest_into_package_dir) ... ok

----------------------------------------------------------------------
Ran 72 tests in 27.099s

OK

Tests run: 72, failures: 0, errors: 0, skipped: 0
SUITE: PASS
```

### 14.2 全量原始输出（`tests/test-output-rc4-hotfix2.txt`，末尾汇总）

```
test_gate_removes_stale_sha256_on_failure (test_release_gate.TestReleaseGate.test_gate_removes_stale_sha256_on_failure)
A pre-existing .sha256 must not survive a failed run — ... ok
test_gate_writes_manifest_into_package_dir (test_release_gate.TestReleaseGate.test_gate_writes_manifest_into_package_dir) ... ok
----------------------------------------------------------------------
Ran 151 tests in 45.328s
OK
Tests run: 151, failures: 0, errors: 0, skipped: 0
SUITE: PASS
```

## 15. RC4-hotfix4：ATTEMPT-07 的 3 个缺陷 + P1–P4（2026-11-20）

ChatGPT 的 HOTFIX3 静态验收通过后，Windows 真机测试 ATTEMPT-05/06/07 均为部分通过。ATTEMPT-07（2026-11-20 21:21）留下三个缺陷：B2 真实发送其实成功了但系统仍报 send_unconfirmed；B3 页面上有回复但 read_latest 返回 found=false；B4 最小化后台发送未通过。Leo 于 21:24 授权修复。ChatGPT 的 ROUND-22 回复（21:31）批准修复范围，给出精确的源码位置，并正式把 GATE-SEAMLESS-CONTINUITY 加为发布门（PENDING）。

修复（见 `docs/CHANGELOG.md` 的 hotfix4 节）：B2 发送顺序（先填内容、等按钮出现、一次点击）、确认超时 10 秒 + reply_started 旁证、health 在输入框为空时 ok:true、read_latest 的 textContent/父级容器回退 + 3 秒重试（不重新引入 "article" 兜底）、background.js 会话固定绑定、BAT 清单验证改用 Python JSON 解析（verify_manifest.py）+ %TEMP% 解析成长路径（resolve_long_path.py）、B5 拆为 B5-A/B5-B。**诚实标注：read_latest / send 修复只在模拟 DOM + 单元测试里验证过（本机没有真实 Chrome/Windows），真实页面验证需 ChatGPT 的 ATTEMPT-08 重测。**

### 15.1 测试结果（2026-11-20，Dash 本地）

batch 1：23 项，0 失败，SUITE: PASS（5.6 秒）；batch 2：56 项，0 失败，SUITE: PASS（12.6 秒）；batch 3：88 项（原 74 项 + background_js 1 项 + verify_manifest 13 项），0 失败，SUITE: PASS（72.0 秒）；全量：167 项，0 失败，0 错误，0 跳过，SUITE: PASS（90.3 秒）。原始输出见 `tests/test-output-rc4-batch-{1,2,3}.txt` / `tests/test-output-rc4.txt`。另做：`py_compile` 全部 Python 文件通过；`manifest.json` 合法 JSON；content.js 与 background.js 通过 `node --check`；密钥扫描干净（只有 localhost stub / 测试里的 test-token-123；包内无 Leo 的密码、Cookie、会话令牌或个人聊天内容）；ZIP 里无 `__pycache__` / `.pyc`；发布门在好包上通过、在故意去掉 .exe 的坏包上拒绝（非零退出、无 .sha256、无 ZIP，预先放好的旧 ZIP/.sha256 也被删掉）。

发布门结果：ZIP `agent-relay-skill-v1.0.0-rc4-hotfix4.zip`（407,096 字节，91 项），SHA-256 `61d092c8c5ab969eeefe86a7a0a82ea00f34d0ab81e0db29ff35c3d56d578e7b`；MANIFEST.json 73 个文件；.exe 224,515 字节，SHA-256 `0e6a9748685d48e435a7f07775bdb9ba020f1348661a154b9276e3bc37bf36de`，与清单一致；清单在包目录与 ZIP 里逐字节一致；check_package 对包目录与 ZIP 都通过。

### 15.2 全量原始输出（`tests/test-output-rc4.txt`，末尾汇总）

```
Ran 167 tests in 90.345s
OK
Tests run: 167, failures: 0, errors: 0, skipped: 0
SUITE: PASS
```
