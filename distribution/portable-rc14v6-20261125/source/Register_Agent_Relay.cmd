@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
echo Agent Relay RC14-v6 Portable - Register Native Host
echo No admin rights required. No file copying or software install.
py -3 --version >nul 2>&1
if not errorlevel 1 goto PYLAUNCH
python --version >nul 2>&1
if not errorlevel 1 goto PYTHON
echo ERROR: Python 3.8+ is required by the existing Native Host.
echo Install Python from the official python.org website first.
set "RC=2"
goto DONE
:PYLAUNCH
py -3 "%~dp0portable_host.py" register %*
set "RC=%ERRORLEVEL%"
goto DONE
:PYTHON
python "%~dp0portable_host.py" register %*
set "RC=%ERRORLEVEL%"
:DONE
echo.
if not "%RC%"=="0" echo Registration did not complete. Review the message above.
pause
exit /b %RC%