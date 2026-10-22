@echo off
cd /d "%~dp0"
title MediAssist Server
rem Open access for now: no sign-in screen, everyone is the owner. Delete the next line before real use.
set MEDIASSIST_OPEN=1
if not exist data\mediassist.db (
  choice /M "First run. Load DEMO data (4 branches, staff, patients, stock, 30 days of history)"
  if errorlevel 2 (python server.py) else (python server.py --demo)
) else (
  python server.py
)
pause
