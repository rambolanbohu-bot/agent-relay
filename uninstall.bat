@echo off
REM ============================================================
REM  Agent Relay Skill v1.0.0-rc4 — Windows 卸载助手
REM
REM  本文件只是一个启动器：找到 Python，然后调用 uninstall.py。
REM  卸载只清理本次安装创建的资源（读 install-manifest.json），
REM  注册表项只在它仍指向本次安装时才删，安装时覆盖过的旧值
REM  会恢复回去。详见 uninstall.py。
REM
REM  RC3 修复（.bat 延迟展开 bug，RC2 里漏网的）：
REM  RC2 的 uninstall.bat 在同一个括号块里先 set DST 再用
REM  %DST:~0,-1%，读到的是块开始前的值（空）。RC3 里本文件
REM  不再在块内读写同一个变量：用 setlocal EnableDelayedExpansion
REM  并在块内一律用 !VAR!。
REM
REM  用法：双击本文件。--keep-state 会先把讨论记录备份到桌面。
REM  注意：本脚本尚未在 Windows 上实测；也可以直接手动删掉
REM  agent-relay-skill 文件夹（但那样注册表项要手动清理）。
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

REM --- 调用真正的卸载器（本文件就在 skill 文件夹里） ---
set "SRC=%~dp0"
if not exist "!SRC!uninstall.py" (
  echo [错误] 找不到 uninstall.py：!SRC!uninstall.py
  echo 请确认本文件在 agent-relay-skill 文件夹里。
  pause
  exit /b 1
)
!PY! "!SRC!uninstall.py" %*
set "RC=!ERRORLEVEL!"
if not "!RC!"=="0" (
  echo.
  echo 卸载没有完成（上面有原因）。
  pause
  exit /b !RC!
)
pause
endlocal
