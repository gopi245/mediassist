# Deploying MediAssist for real use

## 1. Where to run it
All branches must reach one server. Use a small cloud VM (2 vCPU, 4 GB RAM is enough for
several branches) in an Indian region, or a PC with a static IP at the main hospital.

```
python server.py            # listens on port 8000
```
Set `MEDIASSIST_DATA=/srv/mediassist-data` to keep the database, uploads and backups
outside the code folder.

## 2. HTTPS (required)
Never expose port 8000 to the internet directly. Put Caddy in front; it gets a free
certificate automatically. Install Caddy, point your domain's DNS at the server, and use
this `Caddyfile`:

```
care.example.com {
    reverse_proxy 127.0.0.1:8000 {
        header_up X-Forwarded-Proto https
    }
}
```
Then start the app with `HOST=127.0.0.1 TRUST_PROXY=1 python server.py` so only Caddy can reach it
(`TRUST_PROXY=1` makes the app believe Caddy's `X-Forwarded-For` / `X-Forwarded-Proto` headers; leave it
unset when clients connect directly, or anyone could spoof their address), and
set **Admin › Settings › Public address** to `https://care.example.com` (used in booking,
follow-up and feedback links).

Keep it running: on Linux create a systemd service; on Windows use Task Scheduler
("At startup", run START.bat) or NSSM to install it as a service.

## 3. Backups
- A backup is written to `data/backups` every day and kept for 30 days (Admin › Settings).
- Copy that folder off the server every day (cloud storage, or a second machine).
- Test a restore every month: stop the server, copy a backup over `data/mediassist.db`, start.

## 4. Messaging
- **Email:** Gmail with an App password, or your domain's SMTP.
- **WhatsApp:** Twilio. The sandbox works for testing. For patients you need a WhatsApp
  Business number and Meta-approved message templates (appointment reminder, lab report
  ready, feedback). Until then, unsent messages appear in Reports › Messages with a
  "Send by hand" link.

## 5. Legal checklist (India)
- **DPDP Act 2023:** consent is recorded at registration; export and erase are in the
  patient screen. Publish a privacy notice and name a grievance officer.
- **ABDM:** the ABHA number is stored. Live ABHA creation/verification and health-record
  linking need registration on the ABDM sandbox (sandbox.abdm.gov.in) and certification
  before production. This is a separate integration project.
- **Drugs and Cosmetics Rules:** Schedule H/H1 sales need a prescription; the H1 register
  export must be kept for 3 years; Schedule X needs a separate narcotics register.
- **GST:** the GSTR-1 working file and HSN summary are generated; file through the GST
  portal or your CA. Healthcare services are exempt; check room rent above ₹5,000/day.
- **Clinical Establishments Act / NABH:** keep discharge summaries and medical records
  for the required retention period; the system never hard-deletes clinical records.

## 6. Drug database
The safety rules cover common allergies, interactions, conditions and dose limits for the
medicines in the master. For full coverage, license a drug database (for example CIMS or
Medscape) and load its interaction and dose data into the medicine master and
`app/safety.py`.

## 7. Scaling up
SQLite with WAL handles a group of a few branches comfortably. For many busy branches,
move to PostgreSQL: the SQL is plain and the schema is in `app/schema.py`.
