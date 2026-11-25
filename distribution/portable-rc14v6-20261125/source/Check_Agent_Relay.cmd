@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
py -3 --version >nul 2>&1
if not errorlevel 1 goto PYLAUNCH
python --version >nul 2>&1
if not errorlevel 1 goto PYTHON
echo ERROR: Python 3.8+ required.
set "RC=2"
goto DONE
:PYLAUNCH
py -3 "%~dp0portable_host.py" status %*
set "RC=%ERRORLEVEL%"
goto DONE
:PYTHON
python "%~dp0portable_host.py" status %*
set "RC=%ERRORLEVEL%"
:DONE
pause
exit /b %RC%