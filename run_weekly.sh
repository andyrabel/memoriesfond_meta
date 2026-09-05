#!/usr/bin/env bash
# Weekly entry point, invoked by a Windows Task Scheduler task via wsl.exe
# (this repo lives inside WSL, so the .bat / .venv\Scripts layout in
# CLAUDE.md doesn't apply on this machine — see run_weekly.bat for the
# Windows-native equivalent if the repo is ever checked out there).
#
# Plans upcoming posts from the archive (selector.py's rotation) then
# schedules them on Facebook up to selector.MAX_SCHEDULE_DAYS out.
set -uo pipefail
cd "$(dirname "$0")"
mkdir -p logs

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
  ./.venv/bin/python scheduler.py plan
  echo "plan exit code: $?"
  ./.venv/bin/python scheduler.py schedule
  echo "schedule exit code: $?"
} >> logs/weekly.log 2>&1
