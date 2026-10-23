"""Versioned schema. Each migration runs once, in order, inside a transaction.
Add new migrations to the end; never edit one that has shipped."""

MIGRATIONS = [
# 1: foundation, clinical, pharmacy, billing, lab, appointments, IPD, accounts, ops
r"""
CREATE TABLE branches(id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
  address TEXT, phone TEXT, gstin TEXT, dl_no TEXT, report_email TEXT, report_whatsapp TEXT, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT, role TEXT NOT NULL,
  branch_id INTEGER REFERENCES branches(id), reg_no TEXT, email TEXT, whatsapp TEXT, salt TEXT NOT NULL, pw TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1, totp_secret TEXT, payout_pct REAL NOT NULL DEFAULT 0, lang TEXT NOT NULL DEFAULT 'en',
  failed_logins INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0);
CREATE TABLE sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  branch_id INTEGER NOT NULL DEFAULT 0, expires REAL NOT NULL, mfa_ok INTEGER NOT NULL DEFAULT 1);
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE audit(id INTEGER PRIMARY KEY, at TEXT NOT NULL, user_id INTEGER, branch_id INTEGER, action TEXT NOT NULL, detail TEXT);
CREATE TABLE report_log(id INTEGER PRIMARY KEY, sent_at TEXT, day TEXT, kind TEXT, target TEXT, channel TEXT, ok INTEGER, detail TEXT);
CREATE TABLE idempotency(key TEXT PRIMARY KEY, at REAL NOT NULL, status INTEGER NOT NULL, response TEXT NOT NULL);
CREATE TABLE error_log(id INTEGER PRIMARY KEY, at TEXT, method TEXT, path TEXT, error TEXT);

CREATE TABLE patients(id INTEGER PRIMARY KEY, name TEXT NOT NULL, age INTEGER, dob TEXT, gender TEXT, phone TEXT NOT NULL,
  address TEXT, allergies TEXT, conditions TEXT, blood_group TEXT, abha TEXT, weight REAL, lmp TEXT, lang TEXT,
  branch_id INTEGER, created_at TEXT NOT NULL, created_by INTEGER, consent_at TEXT, consent_by INTEGER,
  whatsapp_ok INTEGER NOT NULL DEFAULT 1, erased_at TEXT);
CREATE INDEX ix_pat_phone ON patients(phone);
CREATE TABLE icd10(code TEXT PRIMARY KEY, title TEXT NOT NULL);
CREATE TABLE problems(id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id), icd TEXT, title TEXT NOT NULL,
  since TEXT, status TEXT NOT NULL DEFAULT 'active', created_at TEXT, created_by INTEGER);
CREATE TABLE vitals(id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id), at TEXT NOT NULL, source TEXT, ref_id INTEGER,
  temp REAL, pulse INTEGER, bp_sys INTEGER, bp_dia INTEGER, spo2 INTEGER, weight REAL, sugar REAL, recorded_by INTEGER);
CREATE INDEX ix_vitals ON vitals(patient_id, at);
CREATE TABLE vaccinations(id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id), vaccine TEXT NOT NULL,
  dose TEXT, given_on TEXT NOT NULL, batch TEXT, given_by INTEGER, due_next TEXT);
CREATE TABLE templates(id INTEGER PRIMARY KEY, name TEXT NOT NULL, diagnosis TEXT, icd TEXT, advice TEXT, items TEXT, tests TEXT, followup_days INTEGER);

CREATE TABLE appointments(id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL, patient_id INTEGER NOT NULL REFERENCES patients(id),
  doctor_id INTEGER, day TEXT NOT NULL, slot TEXT, token INTEGER, status TEXT NOT NULL DEFAULT 'booked', source TEXT,
  created_at TEXT, created_by INTEGER, reminder_sent INTEGER NOT NULL DEFAULT 0, visit_id INTEGER, note TEXT);
CREATE INDEX ix_appt ON appointments(branch_id, day);

CREATE TABLE visits(id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id), branch_id INTEGER NOT NULL,
  doctor_id INTEGER, appointment_id INTEGER, created_at TEXT NOT NULL, created_by INTEGER, complaint TEXT,
  temp REAL, pulse INTEGER, bp_sys INTEGER, bp_dia INTEGER, spo2 INTEGER, weight REAL, sugar REAL,
  triage TEXT, triage_reasons TEXT, diagnosis TEXT, icd TEXT, notes TEXT, followup TEXT,
  status TEXT NOT NULL DEFAULT 'waiting', completed_at TEXT);
CREATE INDEX ix_visits ON visits(branch_id, created_at);
CREATE INDEX ix_visits_pat ON visits(patient_id);

CREATE TABLE medicines(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, generic TEXT, form TEXT, schedule TEXT NOT NULL DEFAULT 'OTC',
  gst_pct REAL NOT NULL DEFAULT 5, hsn TEXT, reorder_level INTEGER NOT NULL DEFAULT 50, pack_size INTEGER NOT NULL DEFAULT 1,
  barcode TEXT, strength_mg REAL, max_daily_mg REAL, ped_mg_per_kg_day REAL, renal_caution INTEGER NOT NULL DEFAULT 0,
  pregnancy_avoid INTEGER NOT NULL DEFAULT 0, cold_chain INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1);
CREATE INDEX ix_med_barcode ON medicines(barcode);
CREATE TABLE rx_items(id INTEGER PRIMARY KEY, visit_id INTEGER REFERENCES visits(id), admission_id INTEGER,
  medicine_id INTEGER NOT NULL REFERENCES medicines(id), dose TEXT, freq TEXT, days INTEGER, qty INTEGER NOT NULL,
  instructions TEXT, dispensed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE suppliers(id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT, gstin TEXT, email TEXT);
CREATE TABLE purchase_orders(id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL, supplier_id INTEGER, created_at TEXT, status TEXT NOT NULL DEFAULT 'draft',
  user_id INTEGER, note TEXT);
CREATE TABLE po_items(id INTEGER PRIMARY KEY, po_id INTEGER NOT NULL REFERENCES purchase_orders(id), medicine_id INTEGER NOT NULL, qty INTEGER NOT NULL, received INTEGER NOT NULL DEFAULT 0);
CREATE TABLE purchases(id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL, supplier_id INTEGER, po_id INTEGER, invoice_no TEXT, created_at TEXT,
  user_id INTEGER, total_p INTEGER NOT NULL DEFAULT 0, gst_p INTEGER NOT NULL DEFAULT 0);
CREATE TABLE batches(id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL REFERENCES branches(id), medicine_id INTEGER NOT NULL REFERENCES medicines(id),
  batch TEXT, expiry TEXT NOT NULL, opened TEXT, qty INTEGER NOT NULL CHECK(qty>=0), mrp_p INTEGER NOT NULL, cost_p INTEGER NOT NULL DEFAULT 0,
  rack TEXT, purchase_id INTEGER, received_at TEXT);
CREATE INDEX ix_batches ON batches(branch_id, medicine_id);
CREATE TABLE stock_moves(id INTEGER PRIMARY KEY, at TEXT NOT NULL, branch_id INTEGER NOT NULL, batch_id INTEGER NOT NULL, change INTEGER NOT NULL,
  reason TEXT NOT NULL, ref TEXT, user_id INTEGER);
CREATE TABLE bills(id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL, bill_no TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL, patient_id INTEGER,
  customer TEXT, visit_id INTEGER, admission_id INTEGER, doctor_name TEXT, doctor_reg TEXT, subtotal_p INTEGER NOT NULL, discount_p INTEGER NOT NULL DEFAULT 0,
  gst_p INTEGER NOT NULL DEFAULT 0, total_p INTEGER NOT NULL, pay_mode TEXT, user_id INTEGER, returned_p INTEGER NOT NULL DEFAULT 0, offline_key TEXT);
CREATE INDEX ix_bills ON bills(branch_id, created_at);
CREATE TABLE bill_items(id INTEGER PRIMARY KEY, bill_id INTEGER NOT NULL REFERENCES bills(id), medicine_id INTEGER NOT NULL, batch_id INTEGER NOT NULL,
  qty INTEGER NOT NULL, mrp_p INTEGER NOT NULL, gst_pct REAL, net_p INTEGER NOT NULL, gst_p INTEGER NOT NULL DEFAULT 0, rx_item_id INTEGER,
  returned INTEGER NOT NULL DEFAULT 0);
CREATE TABLE supplier_returns(id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL, supplier_id INTEGER, created_at TEXT, user_id INTEGER, reason TEXT,
  total_p INTEGER NOT NULL DEFAULT 0, credit_note_no TEXT, status TEXT NOT NULL DEFAULT 'sent');
CREATE TABLE supplier_return_items(id INTEGER PRIMARY KEY, return_id INTEGER NOT NULL REFERENCES supplier_returns(id), batch_id INTEGER NOT NULL,
  qty INTEGER NOT NULL, cost_p INTEGER NOT NULL);
CREATE TABLE temp_logs(id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL, at TEXT NOT NULL, fridge TEXT NOT NULL, temp_c REAL NOT NULL, ok INTEGER NOT NULL, user_id INTEGER, note TEXT);
CREATE TABLE stock_counts(id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL, created_at TEXT, user_id INTEGER, status TEXT NOT NULL DEFAULT 'open', closed_at TEXT);
CREATE TABLE stock_count_items(id INTEGER PRIMARY KEY, count_id INTEGER NOT NULL REFERENCES stock_counts(id), batch_id INTEGER NOT NULL, system_qty INTEGER NOT NULL, counted_qty INTEGER);

CREATE TABLE services(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, cat TEXT NOT NULL, rate_p INTEGER NOT NULL, gst_pct REAL NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE invoices(id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL, inv_no TEXT UNIQUE NOT NULL, patient_id INTEGER NOT NULL REFERENCES patients(id),
  visit_id INTEGER, admission_id INTEGER, doctor_id INTEGER, created_at TEXT NOT NULL, user_id INTEGER, kind TEXT NOT NULL DEFAULT 'opd',
  sub_p INTEGER NOT NULL, discount_p INTEGER NOT NULL DEFAULT 0, gst_p INTEGER NOT NULL DEFAULT 0, total_p INTEGER NOT NULL,
  cancelled_at TEXT, cancel_reason TEXT, notes TEXT);
CREATE INDEX ix_inv ON invoices(branch_id, created_at);
CREATE TABLE invoice_items(id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES invoices(id), service_id INTEGER, name TEXT NOT NULL, cat TEXT,
  qty REAL NOT NULL, rate_p INTEGER NOT NULL, disc_p INTEGER NOT NULL DEFAULT 0, gst_pct REAL NOT NULL DEFAULT 0, amount_p INTEGER NOT NULL, ref TEXT);
CREATE TABLE payments(id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL, invoice_id INTEGER, admission_id INTEGER, at TEXT NOT NULL, mode TEXT NOT NULL,
  amount_p INTEGER NOT NULL, ref TEXT, user_id INTEGER, kind TEXT NOT NULL DEFAULT 'payment');
CREATE INDEX ix_pay ON payments(branch_id, at);
CREATE TABLE claims(id INTEGER PRIMARY KEY, invoice_id INTEGER, admission_id INTEGER, patient_id INTEGER NOT NULL, tpa TEXT NOT NULL, policy TEXT, claim_no TEXT,
  icd TEXT, requested_p INTEGER NOT NULL DEFAULT 0, approved_p INTEGER NOT NULL DEFAULT 0, settled_p INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'preauth', created_at TEXT, updated_at TEXT, notes TEXT);
CREATE TABLE claim_events(id INTEGER PRIMARY KEY, claim_id INTEGER NOT NULL REFERENCES claims(id), at TEXT, status TEXT, note TEXT, user_id INTEGER);
CREATE TABLE credit_notes(id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL, cn_no TEXT UNIQUE NOT NULL, invoice_id INTEGER, bill_id INTEGER,
  amount_p INTEGER NOT NULL, reason TEXT, at TEXT, user_id INTEGER, mode TEXT);
CREATE TABLE closings(id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL, day TEXT NOT NULL, expected_p INTEGER, counted_p INTEGER, diff_p INTEGER,
  note TEXT, user_id INTEGER, at TEXT, UNIQUE(branch_id, day));

CREATE TABLE lab_tests(id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, sample TEXT, service_id INTEGER, tat_hours INTEGER, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE lab_params(id INTEGER PRIMARY KEY, test_id INTEGER NOT NULL REFERENCES lab_tests(id), name TEXT NOT NULL, unit TEXT,
  low REAL, high REAL, crit_low REAL, crit_high REAL, ref_text TEXT, sort INTEGER NOT NULL DEFAULT 0);
CREATE TABLE lab_orders(id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL, patient_id INTEGER NOT NULL REFERENCES patients(id), visit_id INTEGER, admission_id INTEGER,
  doctor_id INTEGER, created_at TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'routine', status TEXT NOT NULL DEFAULT 'ordered',
  collected_at TEXT, collected_by INTEGER, resulted_at TEXT, resulted_by INTEGER, verified_at TEXT, verified_by INTEGER, invoice_id INTEGER, note TEXT);
CREATE TABLE lab_order_items(id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES lab_orders(id), test_id INTEGER NOT NULL);
CREATE TABLE lab_results(id INTEGER PRIMARY KEY, order_item_id INTEGER NOT NULL REFERENCES lab_order_items(id), param_id INTEGER NOT NULL,
  value TEXT, num REAL, flag TEXT, UNIQUE(order_item_id, param_id));

CREATE TABLE beds(id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL, ward TEXT NOT NULL, number TEXT NOT NULL, kind TEXT NOT NULL,
  service_id INTEGER, status TEXT NOT NULL DEFAULT 'free', UNIQUE(branch_id, ward, number));
CREATE TABLE admissions(id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL, ip_no TEXT UNIQUE NOT NULL, patient_id INTEGER NOT NULL REFERENCES patients(id),
  bed_id INTEGER, doctor_id INTEGER, admitted_at TEXT NOT NULL, reason TEXT, diagnosis TEXT, icd TEXT, status TEXT NOT NULL DEFAULT 'admitted',
  discharged_at TEXT, discharge_type TEXT, summary TEXT, invoice_id INTEGER, created_by INTEGER);
CREATE TABLE bed_moves(id INTEGER PRIMARY KEY, admission_id INTEGER NOT NULL REFERENCES admissions(id), bed_id INTEGER NOT NULL, from_at TEXT NOT NULL, to_at TEXT);
CREATE TABLE ipd_notes(id INTEGER PRIMARY KEY, admission_id INTEGER NOT NULL REFERENCES admissions(id), at TEXT NOT NULL, user_id INTEGER, kind TEXT NOT NULL, text TEXT NOT NULL);
CREATE TABLE ipd_charges(id INTEGER PRIMARY KEY, admission_id INTEGER NOT NULL REFERENCES admissions(id), at TEXT NOT NULL, service_id INTEGER, name TEXT NOT NULL,
  cat TEXT, qty REAL NOT NULL, rate_p INTEGER NOT NULL, amount_p INTEGER NOT NULL, user_id INTEGER, source TEXT);
CREATE TABLE mar_orders(id INTEGER PRIMARY KEY, admission_id INTEGER NOT NULL REFERENCES admissions(id), medicine_id INTEGER NOT NULL, dose TEXT, route TEXT,
  freq TEXT, times TEXT, start_at TEXT, stop_at TEXT, ordered_by INTEGER, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE mar_admin(id INTEGER PRIMARY KEY, mar_id INTEGER NOT NULL REFERENCES mar_orders(id), due TEXT, at TEXT NOT NULL, status TEXT NOT NULL, user_id INTEGER, note TEXT);

CREATE TABLE expenses(id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL, day TEXT NOT NULL, category TEXT NOT NULL, amount_p INTEGER NOT NULL, mode TEXT,
  vendor TEXT, note TEXT, user_id INTEGER, created_at TEXT);
CREATE TABLE payouts(id INTEGER PRIMARY KEY, doctor_id INTEGER NOT NULL, period TEXT NOT NULL, amount_p INTEGER NOT NULL, paid_at TEXT, mode TEXT, note TEXT, user_id INTEGER,
  UNIQUE(doctor_id, period));
CREATE TABLE attendance(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, branch_id INTEGER, day TEXT NOT NULL, in_at TEXT, out_at TEXT, UNIQUE(user_id, day));
CREATE TABLE feedback(id INTEGER PRIMARY KEY, token TEXT UNIQUE NOT NULL, branch_id INTEGER, patient_id INTEGER, visit_id INTEGER, sent_at TEXT,
  rating INTEGER, comment TEXT, answered_at TEXT);
CREATE TABLE documents(id INTEGER PRIMARY KEY, branch_id INTEGER, patient_id INTEGER, doctor_id INTEGER, bill_id INTEGER, invoice_id INTEGER,
  admission_id INTEGER, lab_order_id INTEGER, claim_id INTEGER, medicine_id INTEGER, batch_id INTEGER, doc_type TEXT NOT NULL, doc_date TEXT,
  note TEXT, filename TEXT, mime TEXT, size INTEGER, path TEXT NOT NULL, created_at TEXT, user_id INTEGER);
CREATE TABLE data_requests(id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL, kind TEXT NOT NULL, at TEXT, user_id INTEGER, done_at TEXT, note TEXT);
CREATE TABLE messages(id INTEGER PRIMARY KEY, at TEXT NOT NULL, kind TEXT, to_addr TEXT, channel TEXT, body TEXT, ok INTEGER, detail TEXT, patient_id INTEGER);
""",
# 2: patient records portal (private links) and documents shared with the patient
r"""
CREATE TABLE portal_links(token TEXT PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id), created_at TEXT NOT NULL, created_by INTEGER,
  expires TEXT NOT NULL, revoked_at TEXT, last_used TEXT, views INTEGER NOT NULL DEFAULT 0);
CREATE INDEX ix_portal_pid ON portal_links(patient_id);
ALTER TABLE documents ADD COLUMN shared_at TEXT
""",
# 3: supplier dues and payments; upload from the phone (QR)
r"""
ALTER TABLE purchases ADD COLUMN due_date TEXT;
ALTER TABLE purchases ADD COLUMN paid_p INTEGER NOT NULL DEFAULT 0;
UPDATE purchases SET paid_p=total_p+gst_p WHERE created_at < date('now','-30 days');
CREATE TABLE supplier_payments(id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL, purchase_id INTEGER NOT NULL REFERENCES purchases(id), supplier_id INTEGER,
  at TEXT NOT NULL, amount_p INTEGER NOT NULL, mode TEXT NOT NULL, ref TEXT, user_id INTEGER);
CREATE TABLE upload_links(token TEXT PRIMARY KEY, branch_id INTEGER, user_id INTEGER NOT NULL, created_at TEXT NOT NULL, expires REAL NOT NULL,
  purpose TEXT NOT NULL, links TEXT);
CREATE TABLE upload_files(id INTEGER PRIMARY KEY, token TEXT NOT NULL, doc_id INTEGER NOT NULL, at TEXT NOT NULL)
""",
# 4: one "patient waiting too long" alert per visit
r"""
ALTER TABLE visits ADD COLUMN wait_alerted INTEGER NOT NULL DEFAULT 0
""",
# 5: AI assistant conversations (per staff member; full API content so follow-ups work)
r"""
CREATE TABLE assistant_chats(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  messages TEXT NOT NULL, turns INTEGER NOT NULL DEFAULT 0)
""",
# 6: offline bills can never be inserted twice; last accepted TOTP step (replay guard); indexes for the dashboards and lookups
r"""
CREATE UNIQUE INDEX ix_bills_offline ON bills(offline_key) WHERE offline_key IS NOT NULL;
ALTER TABLE users ADD COLUMN last_totp INTEGER NOT NULL DEFAULT 0;
CREATE INDEX ix_pay_inv ON payments(invoice_id);
CREATE INDEX ix_pay_adm ON payments(admission_id);
CREATE INDEX ix_rx_visit ON rx_items(visit_id);
CREATE INDEX ix_bill_items ON bill_items(bill_id);
CREATE INDEX ix_moves_batch ON stock_moves(batch_id);
CREATE INDEX ix_audit_at ON audit(at);
CREATE INDEX ix_msg_pat ON messages(patient_id);
CREATE INDEX ix_lab_branch ON lab_orders(branch_id, status);
CREATE INDEX ix_adm_branch ON admissions(branch_id, status);
CREATE INDEX ix_cn ON credit_notes(invoice_id);
CREATE INDEX ix_idem_at ON idempotency(at)
""",
# 7: structured notes and extra vitals, emergency/MLC, credit-bill settlement, lab rejection/amendment/acknowledgement,
#    referrals, procedures with consent, imaging, antenatal visits
r"""
ALTER TABLE bills ADD COLUMN settled_at TEXT;
ALTER TABLE bills ADD COLUMN settled_mode TEXT;
ALTER TABLE bills ADD COLUMN settled_invoice_id INTEGER;
ALTER TABLE visits ADD COLUMN history TEXT;
ALTER TABLE visits ADD COLUMN examination TEXT;
ALTER TABLE visits ADD COLUMN resp_rate INTEGER;
ALTER TABLE visits ADD COLUMN gcs INTEGER;
ALTER TABLE visits ADD COLUMN pain INTEGER;
ALTER TABLE visits ADD COLUMN height REAL;
ALTER TABLE visits ADD COLUMN emergency INTEGER NOT NULL DEFAULT 0;
ALTER TABLE visits ADD COLUMN mlc INTEGER NOT NULL DEFAULT 0;
ALTER TABLE visits ADD COLUMN mlc_no TEXT;
ALTER TABLE visits ADD COLUMN arrival TEXT;
ALTER TABLE visits ADD COLUMN brought_by TEXT;
ALTER TABLE vitals ADD COLUMN resp_rate INTEGER;
ALTER TABLE vitals ADD COLUMN gcs INTEGER;
ALTER TABLE vitals ADD COLUMN pain INTEGER;
ALTER TABLE vitals ADD COLUMN height REAL;
ALTER TABLE lab_orders ADD COLUMN rejections INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lab_orders ADD COLUMN reject_note TEXT;
ALTER TABLE lab_orders ADD COLUMN amended_at TEXT;
ALTER TABLE lab_orders ADD COLUMN amend_reason TEXT;
ALTER TABLE lab_orders ADD COLUMN crit_ack_by INTEGER;
ALTER TABLE lab_orders ADD COLUMN crit_ack_at TEXT;
ALTER TABLE patients ADD COLUMN gravida INTEGER;
ALTER TABLE patients ADD COLUMN para INTEGER;
CREATE TABLE referrals(id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL, patient_id INTEGER NOT NULL REFERENCES patients(id), visit_id INTEGER, admission_id INTEGER,
  at TEXT NOT NULL, by_user INTEGER, to_facility TEXT NOT NULL, to_doctor TEXT, specialty TEXT, urgency TEXT NOT NULL DEFAULT 'routine', reason TEXT NOT NULL,
  summary TEXT, vitals TEXT, treatment_given TEXT, transport TEXT, status TEXT NOT NULL DEFAULT 'sent', outcome TEXT);
CREATE INDEX ix_ref_pat ON referrals(patient_id);
CREATE TABLE procedures(id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL, patient_id INTEGER NOT NULL REFERENCES patients(id), admission_id INTEGER, visit_id INTEGER,
  name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'minor', surgeon_id INTEGER, assistant TEXT, anaesthetist TEXT, anaesthesia TEXT, started_at TEXT, ended_at TEXT,
  indication TEXT, findings TEXT, technique TEXT, implants TEXT, blood_loss TEXT, complications TEXT, post_op TEXT,
  consent_by TEXT, consent_relation TEXT, consent_at TEXT, consent_text TEXT, consent_witness TEXT, created_by INTEGER, created_at TEXT NOT NULL);
CREATE INDEX ix_proc_pat ON procedures(patient_id);
CREATE TABLE imaging(id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL, patient_id INTEGER NOT NULL REFERENCES patients(id), visit_id INTEGER, admission_id INTEGER,
  modality TEXT NOT NULL, study TEXT NOT NULL, ordered_by INTEGER, ordered_at TEXT NOT NULL, indication TEXT, status TEXT NOT NULL DEFAULT 'ordered',
  findings TEXT, impression TEXT, reported_by TEXT, reported_at TEXT, document_id INTEGER);
CREATE INDEX ix_img_pat ON imaging(patient_id);
CREATE TABLE anc_visits(id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id), visit_id INTEGER, at TEXT NOT NULL, by_user INTEGER,
  ga_weeks INTEGER, weight REAL, bp_sys INTEGER, bp_dia INTEGER, fundal_cm REAL, fhr INTEGER, presentation TEXT, urine_albumin TEXT, urine_sugar TEXT,
  hb REAL, oedema INTEGER NOT NULL DEFAULT 0, complaints TEXT, risk TEXT, plan TEXT, next_visit TEXT);
CREATE INDEX ix_anc_pat ON anc_visits(patient_id)
""",
# 8: staff alerts addressed by user id; documents are never hard-deleted; WHO growth reference tables (LMS)
r"""
ALTER TABLE messages ADD COLUMN user_id INTEGER;
CREATE INDEX ix_msg_user ON messages(user_id);
ALTER TABLE documents ADD COLUMN deleted_at TEXT;
ALTER TABLE documents ADD COLUMN deleted_by INTEGER;
CREATE TABLE growth_ref(sex TEXT NOT NULL, kind TEXT NOT NULL, age_months REAL NOT NULL, l REAL NOT NULL, m REAL NOT NULL, s REAL NOT NULL,
  PRIMARY KEY(sex, kind, age_months))
""",
# 9: bed board: when a bed's status last changed (cleaning timers), expected discharge date
r"""
ALTER TABLE beds ADD COLUMN status_at TEXT;
ALTER TABLE beds ADD COLUMN status_note TEXT;
ALTER TABLE admissions ADD COLUMN planned_discharge TEXT
""",
# 10: plain-language interpretation of lab reports (rules or AI), reviewed by the verifying doctor
r"""
ALTER TABLE lab_orders ADD COLUMN interpretation TEXT;
ALTER TABLE lab_orders ADD COLUMN interp_source TEXT;
ALTER TABLE lab_orders ADD COLUMN interp_at TEXT;
ALTER TABLE lab_orders ADD COLUMN interp_reviewed_by INTEGER;
ALTER TABLE lab_orders ADD COLUMN interp_reviewed_at TEXT;
ALTER TABLE lab_orders ADD COLUMN interp_patient INTEGER NOT NULL DEFAULT 1
""",
# 11: walk-in customers can get their bill on WhatsApp too
r"""
ALTER TABLE bills ADD COLUMN customer_phone TEXT
""",
]


def migrate(c):
    c.execute("CREATE TABLE IF NOT EXISTS schema_version(v INTEGER NOT NULL)")
    row = c.execute("SELECT v FROM schema_version").fetchone()
    v = row[0] if row else 0
    if not row:
        c.execute("INSERT INTO schema_version VALUES(0)")
    for i, sql in enumerate(MIGRATIONS[v:], start=v + 1):
        c.execute("BEGIN IMMEDIATE")
        try:
            for stmt in [s for s in sql.split(";\n") if s.strip()]:
                c.execute(stmt)
            c.execute("UPDATE schema_version SET v=?", (i,))
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
    return len(MIGRATIONS)
