# 测试记录（TEST-RECORDS-v7.md）

版本：v1.0.0-rc4-hotfix7。日期：2026-11-21（澳大利亚悉尼时间 AEDT）。本文件只记录已实际验证的内容；未验证的绝不写成已通过，见 `docs/KNOWN-LIMITATIONS.md`。第 1–17 节见 `tests/TEST-RECORDS-v4.md`（第 1–15 节）、`tests/TEST-RECORDS-v5.md`（第 16 节，Hotfix5）与 `tests/TEST-RECORDS-v6.md`（第 17 节，Hotfix6）；本文件只记 Hotfix7。

时间口径：所有时间以运行日志为准，不以 AI 自述时间为准。

## 18. RC4-hotfix7：修 Hotfix6 薄 BAT 的 `py -3` 引用启动缺陷（2026-11-21）

ChatGPT 在新对话“继续Muse项目 Conversation?”的回复（2026-11-21 10:17，思考 37 秒）核验 Hotfix6：ZIP 完整性、Manifest、EXE 已核验，静态测试与单元测试通过；但发现一个具体问题：薄入口 `windows_e2e_test/run_e2e_test.bat` 把 Python 命令存为 `py -3`，执行时却写成 `"!PY!"`，Windows CMD 可能把整个 `py -3` 视为可执行文件名，导致自动测试无法启动；应优先修复，而不是直接宣告 Hotfix6 通过。Leo 于 10:33 授权修这个 BAT 启动问题。

修复（见 `docs/CHANGELOG.md` 的 hotfix7 节）：命令与参数分开存——`PY=py` + `PYARGS=-3`（兜底分支 `PY=python` + `PYARGS=` 为空），调用时命令不带引号（`!PY! !PYARGS! "!PKG!\windows_e2e_test\e2e_runner.py" "!PKG!"`，PKG 路径仍带引号）；BAT 仍为 50 行薄入口（1,861 字节，纯 ASCII，无 BOM、无 CR；GOTO 跳转、无括号块、无 `:log` 子程序、只报退出码 10/11）。B2/B3/B4 识别、adapter.py、content.js、background.js、e2e_runner.py、EXE 全部未动。**诚实标注：BAT 启动修复只在代码检查 + Linux 单元测试里验证过（本机没有真实 Windows CMD），真实 Windows 启动验证需 ChatGPT 的 ATTEMPT-10 重测；至今没有采集到真实的回复节点 DOM 结构。**

### 18.1 诊断证据（代码级复现）

- **BAT 启动**：Hotfix6 的薄入口第 16 行 `set "PY=py -3"`、第 44 行 `"!PY!" "!PKG!\windows_e2e_test\e2e_runner.py" "!PKG!"`。CMD 把带引号的 `"py -3"` 当成一个可执行文件名，runner 永远启动不了（典型 Windows Python 安装里 `py` 启动器都在，BAT 先查 `py`，所以典型机器上必失败；`python` 兜底分支没有空格、引用它不会出问题，但走不到那一步）。这个缺陷从未在真机上触发过：ATTEMPT-09 的 BAT 自动段在更早的阶段就失败了，没走到调 Python 这一步；直接安装/驱动都是绕开 BAT 直接调 Python 的。另：`install.bat` / `uninstall.bat` 同样写 `set "PY=py -3"`，但它们调的是不带引号的 `!PY!`，展开后 `py -3 …` 解析正确，所以不受影响——缺陷只在 E2E 薄入口这一处。
- **旧 BAT 失败演示**（3 项新测试跑 Hotfix6 的 BAT，`/tmp/hotfix7_bat_demo.py`，3 项全失败）：
  - `test_no_quoted_variable_command_with_spaced_value`：`line 44: quoted command 'PY' resolves to 'py -3' (contains a space): "!PY!" "!PKG!\windows_e2e_test\e2e_runner.py" "!PKG!"`
  - `test_runner_invocation_py_branch_parses_to_py_minus_3`：`'py -3' != 'py'`（第一组 PY 赋值必须是裸启动器 `py`，得到 `'py -3'`）
  - `test_runner_invocation_python_fallback_is_plain_python`：`None != ''`（最后一组 PYARGS 赋值必须为空，得到 None——旧 BAT 根本没有 PYARGS）
  
  同一 3 项测试跑 Hotfix7 的 BAT 时**全部通过**。新测试覆盖整类隐患（不只修这一行）：带引号变量作命令时其赋值不得含空格；py 分支调用必须解析为命令 `py` + 参数 `-3`；python 兜底分支必须解析为 plain `python` 且不含 `-3`。

### 18.2 测试结果（2026-11-21，Dash 本地）

batch 1：28 项，0 失败，SUITE: PASS（5.5 秒）；batch 2：56 项，0 失败，SUITE: PASS（12.9 秒）；batch 3：138 项（原 135 项 + bat_cmd_safety 由 10 项增至 13 项），0 失败，SUITE: PASS（131.4 秒）；全量：222 项，0 失败，0 错误，0 跳过，SUITE: PASS（149.4 秒）。原始输出见 `tests/test-output-rc4-batch-{1,2,3}.txt` / `tests/test-output-rc4.txt`。另做：`py_compile` 全部 Python 文件通过；`manifest.json` 合法 JSON；content.js 与 background.js 通过 `node --check`；密钥扫描干净（包内无 Leo 的密码、Cookie、会话令牌或个人聊天内容）；ZIP 里无 `__pycache__` / `.pyc`；发布门在好包上通过（见下）。

发布门结果：ZIP `agent-relay-skill-v1.0.0-rc4-hotfix7.zip`（见随包的 `.sha256` 文件，内含 SHA-256）；MANIFEST.json 80 个文件；.exe 224,515 字节，SHA-256 `0e6a9748685d48e435a7f07775bdb9ba020f1348661a154b9276e3bc37bf36de`，与清单一致；清单在包目录与 ZIP 里逐字节一致；check_package 对包目录与 ZIP 都通过。

### 18.3 构建中间态：MANIFEST 变旧（正常，非失败）

全量第一次跑时 2 项失败，都是 `test_check_package` 的清单哈希不匹配（`docs/CHANGELOG.md` 等 8 个文件在复制 Hotfix6 树后被改过、清单还是 Hotfix6 的旧版）。这是构建流程的正常中间态（Hotfix6 的 TEST-RECORDS-v6.md 第 17.3 节同款）：重新生成 MANIFEST.json 后 `check_package --dir` 即通过；随后分批重跑 28/56/138 项全部通过。最终流程：全部文件定稿 → 重新生成 MANIFEST.json → 分批 222 项 0 失败 → 写本文件 → 再重新生成 MANIFEST.json（含本文件）→ 跑发布门。

### 18.4 全量原始输出（`tests/test-output-rc4.txt`，末尾汇总）

```
Ran 222 tests in 149.400s
OK
Tests run: 222, failures: 0, errors: 0, skipped: 0
SUITE: PASS
```
