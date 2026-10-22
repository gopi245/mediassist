# MediAssist Clinic Server

Shared clinic system: patient register, medicine stock & expiry, dispensing,
staff logins, and an automatic end-of-day report to the doctor (email + WhatsApp).

## Start
1. Install Python 3 (python.org) if the computer doesn't have it.
2. Double-click **START.bat** (or run `python server.py`).
3. Open http://localhost:8000. Other computers on the same Wi-Fi use the
   address printed in the window (e.g. http://192.168.1.20:8000).
4. First run creates `FIRST-LOGIN.txt` with the admin login. Log in,
   click **Change password**, then delete that file.

Keep the server window open during clinic hours; the evening report is sent
by this computer.

## Setup (Settings tab, admin)
- **Doctor email / WhatsApp number** and the time to send the report (default 20:00).
- **Email**: Gmail → turn on 2-step verification → create an App password →
  host `smtp.gmail.com`, port `587`, your Gmail, the app password.
- **WhatsApp**: Twilio account → Messaging → WhatsApp. For testing use the
  Sandbox (the doctor sends the join code to the sandbox number once).
  For daily production use, Twilio/Meta require an approved message template.

## Staff roles
| Role | Can do |
|---|---|
| reception | register and search patients, view reports |
| pharmacy | add stock, dispense, view patients and reports |
| doctor | view patients and reports |
| admin | everything, plus settings and staff logins |

## Backup
Settings → **Download database backup** (do this daily). All data is in `clinic.db`.
