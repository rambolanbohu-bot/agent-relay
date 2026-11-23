@echo off
REM ============================================================
REM  Agent Relay Skill v1.0.0-rc4 — Windows 安装助手
REM
REM  本文件只是一个启动器：找到 Python，然后调用 install.py
REM  做真正的安装（检查、复制、生成 host 清单、写注册表、
REM  生成安装 PIN、写安装清单、失败回滚）。详见 install.py。
REM
REM  RC3 修复（.bat 延迟展开 bug，RC2 里漏网的）：
REM  RC2 的 install.bat 在同一个括号块里先 set SRC 再用
REM  %SRC:~0,-1%，读到的是块开始前的值（空），导致正常安装
REM  路径下 SRC/DST 是空的、robocopy 失败。RC3 里本文件不再
REM  在块内读写同一个变量：用 setlocal EnableDelayedExpansion
REM  并在块内一律用 !VAR!；或者把读写拆到块外面。
REM
REM  用法：解压 ZIP 后，双击本文件（它在 agent-relay-skill
REM  文件夹里）。需要 Python 3.8+（py 启动器或 python.exe）。
REM  注意：本脚本尚未在 Windows 上实测。支持的安装路径是
REM  SKILL.md 里的首次安装向导（在 Muse 里说“安装 Agent Relay”）。
REM ============================================================
setlocal EnableDelayedExpansion

REM --- 找 Python：先 py 启动器，再 python.exe ---
set "PY="
where py >nul 2>nul
if not errorlevel 1 (
  set "PY=py -3"
) else (
  where python >nul 2>nul
  if not errorlevel 1 (
    set "PY=python"
  )
)
if "!PY!"=="" (
  echo [错误] 没找到 Python。
  echo 请先从 python.org 装 Python 3.8 或更新版本，
  echo 安装时勾选 "Add python.exe to PATH"，然后再运行本文件。
  pause
  exit /b 1
)

REM --- 调用真正的安装器（本文件就在 skill 文件夹里） ---
set "SRC=%~dp0"
if not exist "!SRC!install.py" (
  echo [错误] 找不到 install.py：!SRC!install.py
  echo 请确认本文件在 agent-relay-skill 文件夹里。
  pause
  exit /b 1
)
!PY! "!SRC!install.py" --source "!SRC!" %*
set "RC=!ERRORLEVEL!"
if not "!RC!"=="0" (
  echo.
  echo 安装没有完成（上面有原因）。没有改动你的注册表和文件，
  echo 或者已经回滚。修好问题后可以重新运行本文件。
  pause
  exit /b !RC!
)
pause
endlocal
