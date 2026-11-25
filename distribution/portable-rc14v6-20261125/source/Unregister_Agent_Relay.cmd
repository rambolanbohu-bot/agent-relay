@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
echo Agent Relay RC14-v6 Portable - Unregister Native Host
echo Your data, local PIN and files will NOT be deleted.
py -3 --version >nul 2>&1
if not errorlevel 1 goto PYLAUNCH
python --version >nul 2>&1
if not errorlevel 1 goto PYTHON
echo ERROR: Python 3.8+ required.
set "RC=2"
goto DONE
:PYLAUNCH
py -3 "%~dp0portable_host.py" unregister %*
set "RC=%ERRORLEVEL%"
goto DONE
:PYTHON
python "%~dp0portable_host.py" unregister %*
set "RC=%ERRORLEVEL%"
:DONE
echo.
pause
exit /b %RC%