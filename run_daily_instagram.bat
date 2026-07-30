@echo off
rem Daily entry point for Windows Task Scheduler: publishes any queued post
rem whose scheduled_publish_time has arrived to Instagram. Separate from
rem run_weekly.bat because Instagram content publishing has no
rem scheduled_publish_time equivalent — media_publish makes a post live the
rem moment it's called, so this has to run on the actual day rather than
rem up-front alongside Facebook's scheduling. See CLAUDE.md for how to
rem register this with schtasks.

setlocal
cd /d "%~dp0"

".venv\Scripts\python.exe" scheduler.py publish-instagram
if errorlevel 1 goto :error

exit /b 0

:error
echo run_daily_instagram.bat failed — see output above.
exit /b 1
