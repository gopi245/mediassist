# MediAssist v2

One system for a group of hospitals, clinics and medical shops: patient records shared
across branches, OPD and appointments, consultation with safety checks, laboratory,
inpatients, pharmacy, hospital billing with insurance, documents, accounts and reports.

## Start (Windows)
1. Install Python 3.10 or newer from python.org (tick "Add to PATH").
2. Double-click **START.bat**. On the first run say **Y** to load demo data, or **N** for a clean start.
3. Open http://localhost:8000. Logins are in **FIRST-LOGIN.txt**. Sign in, change the
   password, turn on two-step sign-in (My account), then delete that file.

Optional: `pip install anthropic` and add an Anthropic API key in Admin › Settings to let
the AI read photos of bills and supplier invoices.

Run the automated tests: double-click **RUN-TESTS.bat** (end-to-end tests of the API).

## Modules
| Area | What it does |
|---|---|
| Patients | One record across branches, DPDP consent, ABHA number, problem list (ICD-10), vitals charts, vaccinations, pregnancy dates, export and erase on request |
| OPD & appointments | Staff and online booking (`/book?branch=CH`), tokens, check-in, triage board, token TV screen (`/display?branch=CH`), WhatsApp reminders |
| Consultation | Templates, ICD-10, prescriptions with allergy / interaction / condition / child-dose / max-dose / kidney / pregnancy checks, lab orders, printed prescription |
| Laboratory | Worklist, sample collection, results with normal ranges and H/L/critical flags, critical-value alert to the doctor, verification, report to the patient on WhatsApp |
| Inpatients | Bed board, admission with deposit, transfers, doctor rounds and nursing notes, medicine orders and dose record (MAR), charges, running bill, discharge summary and final invoice |
| Pharmacy | Barcode billing, strip or loose tablets, prescriptions from any branch, Schedule H/H1/X rules, offline billing that syncs later, returns with credit notes, H1 register |
| Stock | Racks, expiry, reorder and expiry-rescue suggestions, purchase orders, goods received, supplier returns, fridge temperature log, stock counts, medicine master |
| Hospital billing | Invoices, part payments and dues, refunds, insurance claims (pre-auth → query → approved → settled/rejected), day-end cash closing, service rates |
| Documents | Photos/PDFs linked to patient, doctor, bill, invoice, admission, lab order, claim or stock; optional AI reader |
| Accounts | Profit and loss by branch, expenses, doctor payouts, GSTR-1 working file, Tally XML export |
| Reports | Daily report (patients, revenue, collections, dues, alerts), doctor summary, analytics (busy hours, top diagnoses, repeat patients, no-shows, ratings), feedback, message log; sent automatically every evening |
| Admin | Branches, staff and roles, settings, CSV import of patients and stock, daily backups, audit trail, error log |

Roles: owner, manager, doctor, nurse, reception, pharmacist, lab_tech, accountant.
Screens show in English, Hindi, Telugu or Tamil for navigation and common buttons (My account).

## Before real patients
Read **DEPLOY.md**: HTTPS hosting, backups, and the legal checklist (DPDP, ABDM, drug rules).
Clinical safety checks are keyword and dose-limit rules covering common risks. They support
clinicians; they don't replace a licensed drug database or clinical judgement.
