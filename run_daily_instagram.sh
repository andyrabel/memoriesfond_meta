#!/usr/bin/env bash
# Daily entry point, invoked by a Windows Task Scheduler task via wsl.exe
# (WSL-resident repo — see run_daily_instagram.bat for the Windows-native
# equivalent). Publishes any queued post whose scheduled_publish_time has
# arrived to Instagram; Instagram has no scheduled_publish_time equivalent
# so this must run on the actual day rather than up-front.
set -uo pipefail
cd "$(dirname "$0")"
mkdir -p logs

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
  ./.venv/bin/python scheduler.py publish-instagram
  echo "exit code: $?"
} >> logs/daily_instagram.log 2>&1
