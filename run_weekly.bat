@echo off
rem Weekly entry point for Windows Task Scheduler: plans upcoming posts from
rem the archive (selector.py's rotation logic) then schedules them on
rem Facebook. See CLAUDE.md for how to register this with schtasks.

setlocal
cd /d "%~dp0"

".venv\Scripts\python.exe" scheduler.py plan
if errorlevel 1 goto :error

".venv\Scripts\python.exe" scheduler.py schedule
if errorlevel 1 goto :error

exit /b 0

:error
echo run_weekly.bat failed — see output above.
exit /b 1
