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
| Patient history at the desk | Every consultation opens with previous medicines per visit (one click repeats them), out-of-range results from past reports, lab orders, imaging, admissions and past reactions to medicines; a recorded reaction warns whenever that drug or anything with the same ingredient is prescribed, at the pharmacy counter and on the ward too |
| Consultation | Templates, ICD-10, prescriptions with allergy / interaction / condition / child-dose / max-dose / kidney / pregnancy checks, lab orders, printed prescription |
| Lab billing matches the order | A hospital bill that carries a lab order must bill exactly the tests the doctor ordered, for that patient, once; the counter adds them in one click. Every order shows one timeline: ordered, billed, sample collected, results entered, reviewed by the doctor, critical value acknowledged, report sent, with who and when |
| Lab explanation | Every submitted report gets a plain-language "What this means": each out-of-range value explained in one or two sentences and an overall summary. Rule-based and instant; "Rewrite with AI" polishes the wording when an Anthropic key is set. The verifying doctor edits it and decides whether the patient gets it; it then goes on the PDF and the WhatsApp message, marked as reviewed |
| Laboratory | Worklist, sample collection, results with normal ranges and H/L/critical flags, critical-value alert to the doctor, verification, report to the patient on WhatsApp |
| Bed board | Every bed on one screen for the whole team: free, occupied, cleaning (with timers) and blocked, ward by ward, across branches for the owner, refreshed every 30 s; expected discharges; admit straight from a free bed; dashboard card and alerts for stalled cleaning and no free beds |
| Inpatients | Bed board, admission with deposit, transfers, doctor rounds and nursing notes, medicine orders and dose record (MAR), charges, running bill, discharge summary and final invoice |
| Bill on WhatsApp | Every saved bill goes to the customer's WhatsApp: registered patients get it through their records link with the PDF attached; walk-ins get a signed link to their bill by entering a number at the counter; status shown on the bill with resend, and a one-tap "open WhatsApp" fallback when the server has no WhatsApp gateway |
| GST | Worked out automatically from each medicine's rate (MRP inclusive): taxable value, CGST and SGST shown live in the cart, on the bill, the receipt and the PDF with HSN; month-end rate-wise and HSN-wise figures and a GSTR-1 working file in Accounts |
| Pharmacy | Barcode billing, strip or loose tablets, prescriptions from any branch, Schedule H/H1/X rules, offline billing that syncs later, returns with credit notes, H1 register |
| Suppliers | One record per supplier: last purchase, items, total, paid, pending and overdue; full purchase history with invoice, batches, prices, payment status, payments and returns; compare what each supplier last charged for a medicine; trace any batch on the shelf back to its supplier, invoice, date and price |
| Find a medicine | Top-bar search by part of a brand, salt or barcode lists every match with the rack to pick from first, quantity, expiry and stock at other branches; rack map of every rack and what is on it, printable for the wall, with one click to give rack-less batches their usual place |
| Stock | Racks, expiry, reorder and expiry-rescue suggestions, purchase orders, goods received, supplier returns, fridge temperature log, stock counts, medicine master |
| Hospital billing | Invoices, part payments and dues, refunds, insurance claims (pre-auth → query → approved → settled/rejected), day-end cash closing, service rates |
| Documents | Photos/PDFs linked to patient, doctor, bill, invoice, admission, lab order, claim or stock; optional AI reader |
| Accounts | Profit and loss by branch, expenses, doctor payouts, GSTR-1 working file, Tally XML export |
| Care records | Referrals with a printed letter, procedure and operation notes with informed consent, imaging orders and reports, antenatal visits with risk flags, growth record for children, critical-result acknowledgement, lab sample rejection and amended reports, emergency and medico-legal flags at arrival |
| Reports | Daily report (patients, revenue, collections, dues, alerts), doctor summary, analytics (busy hours, top diagnoses, repeat patients, no-shows, ratings), feedback, message log; sent automatically every evening |
| Admin | Branches, staff and roles, settings, CSV import of patients and stock, daily backups, audit trail, error log |

Roles: owner, manager, doctor, nurse, reception, pharmacist, lab_tech, accountant.
Screens show in English, Hindi, Telugu or Tamil for navigation and common buttons (My account).

## Before real patients
Read **DEPLOY.md**: HTTPS hosting, backups, and the legal checklist (DPDP, ABDM, drug rules).
Clinical safety checks are keyword and dose-limit rules covering common risks. They support
clinicians; they don't replace a licensed drug database or clinical judgement.
