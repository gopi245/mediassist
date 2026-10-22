# MediAssist

Hospital, clinic and pharmacy management for multi-branch groups in India.

| Folder | What it is |
|---|---|
| `mediassist-pro/` | **The system.** Python server (standard library + SQLite) and web app: OPD, consultations with safety checks, lab, inpatients, pharmacy billing and stock, hospital billing, accounts, reports, patient records portal, PDFs, staff watch, patient tracker, doctor alerts, AI assistant (text and voice). Start with `START.bat`, test with `RUN-TESTS.bat`, deploy with `DEPLOY.md`. |
| `mediassist-artifact/` | Builds the in-browser demo (the same server running in Pyodide). `python mediassist-artifact/build.py` writes `dist/`. |
| `clinic-server/`, `mediassist*.html` | Earlier versions, kept for reference. |

Never commit `mediassist-pro/data/` (patient records, settings and API keys) or `FIRST-LOGIN.txt`.
