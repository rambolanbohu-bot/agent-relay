@echo off
REM Agent Relay Skill v1.0.0-rc4-hotfix7 - Windows E2E test entry.
REM Thin entry only. All stage logic lives in
REM windows_e2e_test/e2e_runner.py. This file only finds Python,
REM locates the package directory, and calls the runner.
REM Usage: run_e2e_test.bat [package directory]
REM With no argument it uses the directory this file is in.
REM
REM This file deliberately uses GOTO jumps instead of bracket
REM blocks. CMD misparses bracket blocks on some Windows code
REM pages and after ASCII translation, which is how the old
REM monolithic BAT skipped from init straight to cleanup on the
REM real machine in ATTEMPT-05, ATTEMPT-08 and ATTEMPT-09.
REM A GOTO jump cannot be confused with a block end.
setlocal EnableDelayedExpansion
REM The launcher command and its flag are stored separately.
REM A quoted command like "py -3" would make CMD look for a
REM program literally named py -3, so invoke it unquoted.
set "PY=py"
set "PYARGS=-3"
where py >nul 2>nul
if not errorlevel 1 goto have_python
set "PY=python"
set "PYARGS="
where python >nul 2>nul
if not errorlevel 1 goto have_python
echo [ERROR] Python not found. Please install Python 3.8+.
pause
exit /b 10
:have_python
set "PKG=%~1"
if not "!PKG!"=="" goto have_pkg
set "PKG=%~dp0"
:have_pkg
if exist "!PKG!\windows_e2e_test\e2e_runner.py" goto have_runner
if exist "!PKG!\agent-relay-skill\windows_e2e_test\e2e_runner.py" goto nested_pkg
echo [ERROR] e2e_runner.py not found in the package directory.
echo Pass the extracted package directory as an argument.
pause
exit /b 11
:nested_pkg
set "PKG=!PKG!\agent-relay-skill"
:have_runner
if exist "!PKG!\transport\agent-relay-host.exe" goto have_exe
echo [ERROR] transport\agent-relay-host.exe not found in the package directory.
pause
exit /b 11
:have_exe
!PY! !PYARGS! "!PKG!\windows_e2e_test\e2e_runner.py" "!PKG!"
exit /b !ERRORLEVEL!
