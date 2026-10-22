@echo off
cd /d "%~dp0"
title MediAssist Server
if not exist data\mediassist.db (
  choice /M "First run. Load DEMO data (4 branches, staff, patients, stock, 30 days of history)"
  if errorlevel 2 (python server.py) else (python server.py --demo)
) else (
  python server.py
)
pause
