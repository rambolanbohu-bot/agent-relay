# Native Messaging host 启动器（v1.0.0-rc4）

Chrome 扩展与 Python 协调器之间的本机一端。Chrome 的 Native
Messaging host 清单 `path` 字段必须指向一个**可执行文件（.exe）**，
不能指向 `.bat` 或 `.py`（Correction 1，ChatGPT RC3 审核）。

## 文件

| 文件 | 作用 |
|---|---|
| `agent-relay-host.exe`（在 `transport/`，和 `native_host.py` 同一个文件夹） | 启动器本体（已编译好）：找到 python.exe，用 `CREATE_NO_WINDOW` 拉起同目录的 `native_host.py`，stdin/stdout 原样透传 Native Messaging 协议 |
| `agent-relay-host.c` | 启动器源码（C，Windows API  only，无网络、无注册表、无 shell） |
| `build_host_exe.bat` | 在真实 Windows 上重新编译启动器（mingw-w64 gcc 或 MSVC cl） |

## 这个 .exe 是怎么来的（可验证）

- 在 Linux 上用 mingw-w64 交叉编译：
  `x86_64-w64-mingw32-gcc -O2 -mwindows -municode -Wall -o agent-relay-host.exe agent-relay-host.c`
- 验证：`file` 显示 `PE32+ executable (GUI) x86-64, for MS Windows`；
  导入表只有 `KERNEL32.dll` 与 `msvcrt.dll`（无注册表、无网络、
  无 shell 执行）；字符串里没有 `.bat` / `cmd.exe` / `powershell`；
  唯一写文件的地方是出错时写 `agent-relay-host.log`（绝不写 stdout，
  stdout 属于协议本身）。
- SHA-256：见 `transport/native_host/agent-relay-host.exe.sha256`。

## 还没验证的（诚实标注）

- **这个 .exe 还没有在真实 Windows 上运行过。**本机没有 Windows，
  也没有 wine；只做了 PE 格式、导入表与字符串检查。真实 Windows
  上的拉起、协议透传、Chrome 扩展往返，仍是 PENDING，
  见 `docs/KNOWN-LIMITATIONS.md`。Windows E2E 在实测通过前不标 PASS。
- 启动器只解决“host 必须是 .exe”这一项；扩展本身也未在真实
  Chrome 里加载测试。

## 启动器做什么 / 不做什么

做：找到 `py.exe`（优先）或 `python.exe`，拉起同目录的
`native_host.py --state-dir <skill>\orchestrator\state\native_host`，
等子进程退出并返回它的退出码；出错只写日志文件。

不做：不读任意文件、不执行系统命令、不碰网络、不碰注册表、
不释放审批、不往 stdout 写任何东西（stdout 是协议通道）。
