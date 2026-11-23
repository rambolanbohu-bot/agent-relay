# Windows 真机端到端测试计划（windows_e2e_test/）

版本：v1.0.0-rc4-hotfix7，2026-11-21。状态：**PENDING**——本机没有 Windows、没有 wine，Windows 真机测试尚未跑过。本计划与脚本只说明“怎么测”，不声称“已通过”。

## 测什么：整条真链路

```
Chrome 扩展 → Native Host EXE → Python 协调器 → 状态记录 → Chrome 扩展
```

每段核对：message_id、ACK、错误处理、超时行为。只测模拟 JSON 返回不算数。

## Hotfix6：阶段状态机（P1）

ATTEMPT-09 证明旧的整块 `.bat` 在真机上会从 init 直接跳到 cleanup（exit 2），安装根本没跑、没有 A 段记录，而 BAT 自身的静态检查拦不住这种控制流故障。因此 Hotfix6 把全部阶段逻辑搬进 Python：

- `run_e2e_test.bat`——**薄入口**：只找 Python、定位包目录、调 `e2e_runner.py`。它用 GOTO 跳转、没有任何括号块、没有任何 `:log` 子程序、纯 ASCII、无 BOM、无 CR——CMD 没有办法把它误解析。ASCII 副本与它字节相同（已是纯 ASCII，无需翻译）。
- `e2e_runner.py`——**阶段状态机**：INIT → PREFLIGHT → INSTALL → MANIFEST → MKEXT → DRIVER → B → CLEANUP。每阶段在日志和 `record\stage-markers.json` 里记起止标记与退出码；任一阶段失败立即中止，绝不静默跳到后一阶段；CLEANUP 一定跑（try/finally），但只在 install 真正完成时才调 `uninstall.py`——安装没完成时只核对“什么都没留下”，绝不对不存在的目录调卸载（这正是 ATTEMPT-09 的故障模式）。
- 退出码：薄 BAT 只报 10（Python 未找到）与 11（包 / runner / .exe 未找到）；runner 报 12–24（见 e2e_runner.py 顶部与 record-template.md）。

其余文件与隔离规则不变（见下）。

## 隔离规则（绝不碰日常配置）

- Chrome 用独立的 `--user-data-dir`（临时 profile），不碰日常 profile、已装扩展、MCP 配置。
- 注册表只写一个测试专用的 host 名 `com.agentrelay.host.e2e`（真实的 `com.agentrelay.host` 不动）；写之前先检查已存在就拒绝；安装前、安装后、卸载后三次核对正式项的值（`fc` 对比记录文件），任何变化即 FAIL；测试结束删掉测试项，只删这一项。
- 安装到 `%TEMP%\agent-relay-e2e-<随机数>\` 下的临时目录，不碰日常安装。
- `.exe` 找不到就拒绝——绝不回退到 `.bat` / `.py` 当 host。

## 文件

- `run_e2e_test.bat`——Windows 薄入口（Hotfix6）：只找 Python、定位包目录、调 `e2e_runner.py`。不含阶段逻辑。
- `e2e_runner.py`——Windows E2E 阶段状态机（Hotfix6，见上）：建隔离目录、检查 Chrome/Python/`.exe`、**跑真正的 `install.py` 安装（测试 host 名）**、用 `verify_manifest.py` 核对清单、**用 `make_test_extension.py` 生成测试扩展**、跑 A 段驱动、启动独立 profile 的 Chrome（加载测试扩展）、打印 B 段清单、**跑真正的 `uninstall.py` 卸载并核对注册表**、清理测试扩展目录。RC4-hotfix FIX 3：安装/卸载不再由脚本手工复制文件和写注册表。
- `make_test_extension.py`——从正式扩展复制一份，只把 `background.js` 的 `HOST_NAME` 换成 `com.agentrelay.host.e2e`，并验证：替换正好 1 次、正式值已清除、`manifest.json` 与 `EXTENSION_ID.txt` 原样不动（扩展 ID 保持 `jeelmedmciafjnfdpnjgbgipplcddhka`，host 清单的 `allowed_origins` 仍然匹配）。失败时删除未建成的目标目录。
- `native_host_driver.py`——A 段协议驱动：拉起真实的 `agent-relay-host.exe`，走长度前缀 JSON 协议，核对 ping 转发、pong 回录、send 的 id/message_id、错误处理（bad_auth / bad_inbox_json / unknown_command_type）、超时与往返时延、干净退出。输出 JSON 记录（`e2e-record-driver.json`）。它在管道那一端扮演扩展，不是真实 Chrome——这一点记录里写明了。
- `record-template.md`——逐项记录模板：每步写命令、输出、时间戳、结果（PASS/FAIL/TIMEOUT/PENDING）、备注。RC4-hotfix 新增安装/卸载核对表（I1–I4、U1–U4）。Hotfix6 新增诊断表（D1 脱敏 DOM 采集、D2 最小化按钮时间序列）与阶段标记记录 `stage-markers.json`。

## 安装 / 卸载（自动，真正的 install.py / uninstall.py）

`e2e_runner.py` 依次跑：

| # | 步骤 | 判定 |
|---|---|---|
| I1 | `install.py --source <包> --dest <临时安装> --host-name com.agentrelay.host.e2e --non-interactive` | 退出码 0 即 PASS（失败则安装回滚、无改动） |
| I2 | 测试注册表项存在且指向生成的清单；清单 `name` 是 `com.agentrelay.host.e2e`，`allowed_origins` 含扩展 ID | 一致即 PASS |
| I3 | 正式注册表项 `com.agentrelay.host` 安装后与安装前 `fc` 对比 | 相同即 PASS，不同即 FAIL |
| I4 | `make_test_extension.py` 生成测试扩展 | 退出码 0、HOST_NAME 已换、manifest 原样即 PASS |
| U1 | `uninstall.py --dest <临时安装> --non-interactive` | 退出码 0 即 PASS |
| U2 | 测试注册表项卸载后消失 | 找不到即 PASS |
| U3 | 正式注册表项卸载后与安装前 `fc` 对比 | 相同即 PASS，不同即 FAIL |
| U4 | 测试扩展目录已删除；临时 profile + 记录保留备查 | 已删即 PASS |

## A 段（自动）：host + 协调器队列协议

`e2e_runner.py` 自动跑 `native_host_driver.py --exe <临时安装>\transport\agent-relay-host.exe`。步骤：

| # | 步骤 | 判定 |
|---|---|---|
| A1 | host 启动，secret 文件出现（10 秒内） | 出现即 PASS |
| A2 | ping：inbox 命令 → stdout 转发，nonce 一致 | 转发且 nonce 一致即 PASS |
| A3 | pong：stdin 回包 → outbox 记盘，nonce 一致 | 记盘即 PASS（完成一整圈） |
| A4 | send：转发的 envelope 保留 id 与 message_id | 一致即 PASS |
| A5 | 错误处理：错 auth → bad_auth；坏行 → bad_inbox_json；未知类型 → unknown_command_type | 逐项记盘即 PASS |
| A6 | 超时：每步等回复设 5 秒 deadline，超时记 TIMEOUT；量往返时延 | 无 TIMEOUT 即 PASS |
| A7 | shutdown：host 干净退出（5 秒内，退出码 0） | 退出码 0 即 PASS |

## B 段（手动）：真实 Chrome

脚本启动独立 profile 的 Chrome 后，操作员按 `record-template.md` 做：

| # | 步骤 | 判定 |
|---|---|---|
| B1 | 打开 chrome://extensions，确认扩展已加载、无错误 | 无错误即 PASS |
| B2 | 打开 chatgpt.com（已登录），用扩展发一条测试消息；确认协调器日志里出现同一 message_id | message_id 一致即 PASS |
| B3 | 等 ChatGPT 回复；确认回复回到扩展并记盘（message_id、时间、内容哈希） | 回录一致即 PASS |
| B4 | 把另一个窗口放到前台，再发一条消息；确认 Chrome 没有蹦到前台、键盘鼠标没有被抢 | 无前台切换、无抢占即 PASS |
| B5 | 关掉 ChatGPT 标签页再重开；确认扩展重连、不断点续跑（或如实记录失败） | 重连成功即 PASS |

## 通过标准

安装/卸载核对（I1–I4、U1–U4）全部 PASS、A 段全部 PASS 且 B 段全部 PASS，Windows E2E 才能标 PASS。任何一段 FAIL/TIMEOUT/PENDING，整体就是 PENDING（或 FAIL），不写 PASS。

## 预检（Linux 上已做，不等于 Windows 通过）

`native_host_driver.py --python-host transport/native_host.py` 在 Linux 上对 Python host 跑过：8 步全 PASS。这只证明驱动脚本本身的逻辑是对的，不证明 Windows 真链路。
