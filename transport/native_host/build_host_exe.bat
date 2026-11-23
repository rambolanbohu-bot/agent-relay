@echo off
REM ============================================================
REM  Agent Relay Skill v1.0.0-rc4 — 在真实 Windows 上重新编译
REM  Native Messaging host 启动器 agent-relay-host.exe。
REM
REM  用法：双击本文件，或在命令行运行 build_host_exe.bat。
REM  本文件只在你要重新编译启动器时用；正常安装不需要运行它，
REM  因为包里已经带了一个在 Linux 上用 mingw-w64 交叉编译好的
REM  agent-relay-host.exe（见 transport/native_host/README.md）。
REM
REM  需要的工具（二选一）：
REM    A) mingw-w64（推荐）：gcc 在 PATH 里，例如装了 MSYS2 / mingw-w64。
REM    B) MSVC：装了 Visual Studio 的“使用 C++ 的桌面开发”，
REM       在“x64 Native Tools Command Prompt”里运行本文件。
REM
REM  编译成功后，把生成的 agent-relay-host.exe 放到
REM  <skill>\transport\ 下面，和 native_host.py 在同一个文件夹。
REM  注意：本脚本不会把启动器指向 .bat 或 .py——host 清单的 path
REM  字段必须永远指向这个 .exe（Correction 1）。
REM ============================================================
setlocal EnableDelayedExpansion
set SRC=%~dp0agent-relay-host.c
REM 输出放到 transport\（和 native_host.py 同一个文件夹），因为
REM 启动器只在自己所在的文件夹里找 native_host.py。
set OUT=%~dp0..\agent-relay-host.exe
if not exist "!SRC!" (
  echo [错误] 找不到 agent-relay-host.c：!SRC!
  pause
  exit /b 1
)

where gcc >nul 2>nul
if not errorlevel 1 (
  echo 找到 mingw-w64 gcc，开始编译 ...
  gcc -O2 -mwindows -municode -Wall -o "!OUT!" "!SRC!"
  if errorlevel 1 (
    echo [错误] gcc 编译失败。
    pause
    exit /b 1
  )
  goto :ok
)

where cl >nul 2>nul
if not errorlevel 1 (
  echo 找到 MSVC cl，开始编译 ...
  cl /O2 /Fe"!OUT!" "!SRC!" /link /SUBSYSTEM:WINDOWS kernel32.lib
  if errorlevel 1 (
    echo [错误] cl 编译失败。
    pause
    exit /b 1
  )
  goto :ok
)

echo [错误] 没找到 gcc 也没找到 cl。
echo 请先装 mingw-w64（MSYS2）或 Visual Studio C++，
echo 然后在对应的命令行里重新运行本文件。
pause
exit /b 1

:ok
if not exist "!OUT!" (
  echo [错误] 编译器退出了，但没有生成 !OUT!
  pause
  exit /b 1
)
echo.
echo 编译成功：!OUT!
echo 请确认它和 native_host.py 在同一个文件夹
echo （<skill>\transport\），然后重启 Chrome 再试扩展连接。
pause
endlocal
