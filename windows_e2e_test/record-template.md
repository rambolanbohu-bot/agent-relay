# Windows E2E 测试记录模板（record-template.md）

每次真机测试填一份。文件放在测试的 record 目录里（`e2e-record-manual.md`）。
结果只写四种：PASS / FAIL / TIMEOUT / PENDING。没跑过的写 PENDING，不写 PASS。

## 测试信息

- 日期时间：
- 测试人：
- 机器：Windows 版本 / Chrome 版本 / Python 版本：
- RC4-hotfix 包 SHA-256：
- 隔离目录：`%TEMP%\agent-relay-e2e-<随机数>\`
- 测试注册表项：`HKCU\...\NativeMessagingHosts\com.agentrelay.host.e2e`（测试后已删除：是 / 否）
- 正式注册表项 `com.agentrelay.host`：安装前 / 安装后 / 卸载后三次核对结果（见下表）

## 安装 / 卸载（自动，真正的 install.py / uninstall.py，FIX 3）

| # | 步骤 | 命令 | 输出 | 时间戳 | 结果 | 备注 |
|---|---|---|---|---|---|---|
| I1 | install.py 安装（测试 host 名） | `install.py --source <包> --dest <临时安装> --host-name com.agentrelay.host.e2e --non-interactive` | 退出码： ；安装 PIN（只记在记录里）： | | | 失败则安装回滚、无改动 |
| I2 | 测试注册表项存在且指向生成的清单 | `reg query ...\com.agentrelay.host.e2e`；`verify_manifest.py`（Python JSON 解析）核对 name/path/allowed_origins，并验证清单文件经长路径和短路径都能访问 | | | | 旧版 findstr 检查已废弃（它把路径错误报成内容错） |
| I3 | 正式注册表项安装后没动 | `fc prod-reg-before.txt prod-reg-after-install.txt` | 相同 / 不同 | | | 不同即 FAIL，立即停 |
| I4 | 测试扩展生成 | `make_test_extension.py --source <包>\transport\extension --dest <临时>\test-extension` | 退出码： ；HOST_NAME 已换：是 / 否；manifest.json 原样：是 / 否 | | | |
| U1 | uninstall.py 卸载 | `uninstall.py --dest <临时安装> --non-interactive` | 退出码： ；注册表动作： | | | |
| U2 | 测试注册表项已消失 | `reg query ...\com.agentrelay.host.e2e` 应找不到 | | | | |
| U3 | 正式注册表项卸载后没动 | `fc prod-reg-before.txt prod-reg-after-uninstall.txt` | 相同 / 不同 | | | 不同即 FAIL |
| U4 | 测试扩展目录已删除；临时 profile + 记录保留备查 | | | | | |

BAT 退出码（Hotfix6：薄 BAT 入口只报 10/11，其余由 `windows_e2e_test/e2e_runner.py` 的阶段状态机报出；见 e2e_runner.py 顶部）：10 Python 未找到（BAT）；11 包 / runner / .exe 未找到，或隔离目录建不起来；12 Chrome 未找到；13 测试注册表项已存在；14 install.py 失败；15 安装后找不到测试注册表项；16 清单内容不匹配；17 清单文件或解析错误；18 清单验证未知退出码；19 安装后正式注册表项变了；20 临时安装里没有 .exe；21 生成测试扩展失败；22 A 段驱动失败；23 Chrome 启动失败；24 清理失败（卸载或清理后核对失败）；0 成功。任一非 0 即停，不要继续 B 段。阶段顺序与起止标记见 `record\stage-markers.json`（INIT → PREFLIGHT → INSTALL → MANIFEST → MKEXT → DRIVER → B → CLEANUP；失败阶段之后绝不出现更晚的阶段——若出现了，就是控制流缺陷，立即停并保留日志）。

## 诊断（Hotfix6 新增，可选只读）

| # | 步骤 | 命令/操作 | 输出/所见 | 时间戳 | 结果 | 备注 |
|---|---|---|---|---|---|---|
| D1 | 脱敏 DOM 采集 | 协调器 `transport/adapter.py` 的 `collect_dom(site, user_marker, assistant_marker)`（扩展 `collect_dom` 命令，只读，不发消息） | user_found： ；assistant_found： ；role_selector_counts.user： ；role_selector_counts.assistant： | | | user_found=true 但 role_selector_counts.user=0，就是用户角色选择器失效的直接证据；助手同理。结果里绝不含消息内容、Cookie、token、URL、真实 message id |
| D2 | 最小化按钮时间序列 | B4 发送结果里的 `button_timeline`（before_input / after_input / during_wait / timeout 或 button_found）+ `visibility_state` | 各采样点的按钮是否存在 / 是否禁用 / 可见性： | | | 区分按钮从未出现 / 出现但禁用 / 出现过又消失 / 状态同步过慢；不要只看“等了多久” |

## A 段（自动，native_host_driver.py）

记录文件：`e2e-record-driver.json`（脚本自动生成，附在本记录后）。

| # | 步骤 | 命令 | 输出 | 时间戳 | 结果 | 备注 |
|---|---|---|---|---|---|---|
| A1 | host 启动 + secret | 见驱动记录 | | | | |
| A2 | ping 转发 | 见驱动记录 | | | | |
| A3 | pong 回录 | 见驱动记录 | | | | |
| A4 | send 的 id/message_id | 见驱动记录 | | | | |
| A5 | 错误处理（3 项） | 见驱动记录 | | | | |
| A6 | 超时与往返时延 | 见驱动记录 | | | | |
| A7 | shutdown 干净退出 | 见驱动记录 | | | | |

A 段总体：PASS / FAIL（驱动退出码： ）

## B 段（手动，真实 Chrome）

| # | 步骤 | 命令/操作 | 输出/所见 | 时间戳 | 结果 | 备注 |
|---|---|---|---|---|---|---|
| B1 | 扩展加载无错误 | 打开 chrome://extensions（加载的是测试扩展目录 `%TEMP%\...\test-extension`） | 扩展 ID： ；应为 jeelmedmciafjnfdpnjgbgipplcddhka | | | | |
| B2 | 发测试消息，message_id 一致 | 扩展没有弹窗 UI：用协调器的 `transport/adapter.py`（health / send / read_latest）指挥扩展发消息；查协调器日志 | 发出的 message_id： ；日志里的 message_id： ；发送结果（message_sent / uncertain / not_sent）： | | | |
| B3 | 回复回录 | 等 ChatGPT 回复；查记盘（adapter.py read_latest） | 回复的 message_id： ；记盘时间： ；内容哈希： ；read_latest 结果（found / not found）： | | | |
| B4 | 不抢前台 | 另一窗口在前台时再发一条 | Chrome 是否蹦到前台： ；键盘鼠标是否被抢： | | | |
| B5-A | 关标签页重连 | 关掉 ChatGPT 标签页（保持独立 Chrome 窗口开着），再重开同一标签页 | 是否重连： ；是否续跑： ；是否换了会话/标签页： | | | |
| B5-B | 整机重启重连 | 完全退出独立 Chrome，再用同一独立配置重启 | 扩展是否重连： ；Host 是否重连： ；队列是否恢复： ；未确认的发送是否按 UNCERTAIN 处理、不自动重发旧消息： | | | |

B 段总体：PASS / FAIL / PENDING

## 总体结论

- Windows E2E：PASS / FAIL / PENDING
- 未通过或未做的项：
- 备注：
