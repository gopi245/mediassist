"""Reference data loaded on first run. Clinical limits are conservative adult/paediatric
defaults for common drugs; replace or extend with a licensed drug database."""

# name, generic, form, schedule, gst%, reorder(units), pack_size, strength_mg, max_daily_mg, ped_mg_per_kg_day, renal_caution, pregnancy_avoid, cold_chain, barcode
MEDICINES = [
    ("Dolo 650", "paracetamol", "Tablet", "OTC", 5, 300, 15, 650, 4000, 60, 0, 0, 0, "8901234500011"),
    ("Crocin Syrup 60ml", "paracetamol", "Syrup", "OTC", 5, 20, 1, None, None, 60, 0, 0, 0, "8901234500028"),
    ("Amoxyclav 625", "amoxicillin clavulanic acid", "Tablet", "H", 5, 60, 6, 625, 3750, 45, 1, 0, 0, "8901234500035"),
    ("Azithral 500", "azithromycin", "Tablet", "H", 5, 30, 3, 500, 500, 10, 0, 0, 0, "8901234500042"),
    ("Cifran 500", "ciprofloxacin", "Tablet", "H", 5, 40, 10, 500, 1500, None, 1, 1, 0, "8901234500059"),
    ("Cefixime 200", "cefixime", "Tablet", "H", 5, 40, 10, 200, 400, 8, 1, 0, 0, "8901234500066"),
    ("Pan 40", "pantoprazole", "Tablet", "H", 5, 100, 15, 40, 80, None, 0, 0, 0, "8901234500073"),
    ("Omez 20", "omeprazole", "Capsule", "H", 5, 60, 15, 20, 40, None, 0, 0, 0, "8901234500080"),
    ("Brufen 400", "ibuprofen", "Tablet", "OTC", 5, 100, 15, 400, 2400, 30, 1, 1, 0, "8901234500097"),
    ("Voveran 50", "diclofenac", "Tablet", "H", 5, 60, 10, 50, 150, None, 1, 1, 0, "8901234500103"),
    ("Ecosprin 75", "aspirin", "Tablet", "OTC", 5, 100, 14, 75, 325, None, 0, 0, 0, "8901234500110"),
    ("Clopilet 75", "clopidogrel", "Tablet", "H", 5, 60, 15, 75, 75, None, 0, 0, 0, "8901234500127"),
    ("Warf 5", "warfarin", "Tablet", "H", 5, 30, 10, 5, 10, None, 0, 1, 0, "8901234500134"),
    ("Glycomet 500", "metformin", "Tablet", "H", 5, 120, 10, 500, 2000, None, 1, 0, 0, "8901234500141"),
    ("Telma 40", "telmisartan", "Tablet", "H", 5, 90, 15, 40, 80, None, 1, 1, 0, "8901234500158"),
    ("Aldactone 25", "spironolactone", "Tablet", "H", 5, 30, 15, 25, 100, None, 1, 1, 0, "8901234500165"),
    ("Atorva 10", "atorvastatin", "Tablet", "H", 5, 60, 15, 10, 80, None, 0, 1, 0, "8901234500172"),
    ("Metrogyl 400", "metronidazole", "Tablet", "H", 5, 40, 15, 400, 2400, 30, 0, 0, 0, "8901234500189"),
    ("Fluconazole 150", "fluconazole", "Tablet", "H", 5, 20, 1, 150, 400, 6, 1, 1, 0, "8901234500196"),
    ("Ultracet", "tramadol paracetamol", "Tablet", "H1", 5, 30, 10, 37.5, 300, None, 1, 1, 0, "8901234500202"),
    ("Fluoxetine 20", "fluoxetine", "Capsule", "H", 5, 30, 10, 20, 80, None, 0, 0, 0, "8901234500219"),
    ("Cetirizine 10", "cetirizine", "Tablet", "OTC", 5, 100, 10, 10, 10, 0.25, 1, 0, 0, "8901234500226"),
    ("Benadryl Syrup 100ml", "diphenhydramine", "Syrup", "OTC", 5, 20, 1, None, None, None, 0, 0, 0, "8901234500233"),
    ("ORS Sachet", "oral rehydration salts", "Sachet", "OTC", 5, 100, 1, None, None, None, 0, 0, 0, "8901234500240"),
    ("Propranolol 40", "propranolol", "Tablet", "H", 5, 30, 15, 40, 320, None, 0, 0, 0, "8901234500257"),
    ("Insulin Glargine", "insulin glargine", "Injection", "H", 5, 10, 1, None, None, None, 0, 0, 1, "8901234500264"),
    ("Ceftriaxone 1g", "ceftriaxone", "Injection", "H", 5, 20, 1, 1000, 4000, 80, 0, 0, 0, "8901234500271"),
]

ICD10 = [("A09", "Infectious gastroenteritis and colitis"), ("B34.9", "Viral infection, unspecified"), ("E11.9", "Type 2 diabetes mellitus without complications"),
    ("E11.65", "Type 2 diabetes mellitus with hyperglycaemia"), ("E03.9", "Hypothyroidism, unspecified"), ("E78.5", "Hyperlipidaemia, unspecified"),
    ("D64.9", "Anaemia, unspecified"), ("F32.9", "Depressive episode, unspecified"), ("F41.1", "Generalised anxiety disorder"), ("G43.9", "Migraine, unspecified"),
    ("H10.9", "Conjunctivitis, unspecified"), ("H66.9", "Otitis media, unspecified"), ("I10", "Essential (primary) hypertension"), ("I20.9", "Angina pectoris, unspecified"),
    ("I21.9", "Acute myocardial infarction, unspecified"), ("I50.9", "Heart failure, unspecified"), ("I63.9", "Cerebral infarction, unspecified"),
    ("J00", "Acute nasopharyngitis (common cold)"), ("J02.9", "Acute pharyngitis, unspecified"), ("J03.9", "Acute tonsillitis, unspecified"),
    ("J06.9", "Acute upper respiratory infection, unspecified"), ("J18.9", "Pneumonia, unspecified organism"), ("J20.9", "Acute bronchitis, unspecified"),
    ("J30.4", "Allergic rhinitis, unspecified"), ("J45.9", "Asthma, unspecified"), ("J44.9", "Chronic obstructive pulmonary disease, unspecified"),
    ("K21.9", "Gastro-oesophageal reflux disease"), ("K29.7", "Gastritis, unspecified"), ("K35.8", "Acute appendicitis, other"), ("K59.0", "Constipation"),
    ("K80.2", "Calculus of gallbladder without cholecystitis"), ("L23.9", "Allergic contact dermatitis"), ("L30.9", "Dermatitis, unspecified"),
    ("M54.5", "Low back pain"), ("M17.9", "Osteoarthritis of knee, unspecified"), ("M79.1", "Myalgia"), ("N18.9", "Chronic kidney disease, unspecified"),
    ("N20.0", "Calculus of kidney"), ("N39.0", "Urinary tract infection, site not specified"), ("O80", "Single spontaneous delivery"),
    ("O24.4", "Gestational diabetes mellitus"), ("Z34.9", "Supervision of normal pregnancy"), ("R50.9", "Fever, unspecified"), ("R51", "Headache"),
    ("R05", "Cough"), ("R10.4", "Abdominal pain, other and unspecified"), ("R11", "Nausea and vomiting"), ("R07.4", "Chest pain, unspecified"),
    ("R06.0", "Dyspnoea"), ("S52.5", "Fracture of lower end of radius"), ("S93.4", "Sprain of ankle"), ("T14.1", "Open wound of unspecified body region"),
    ("A01.0", "Typhoid fever"), ("A90", "Dengue fever"), ("B54", "Malaria, unspecified"), ("A15.0", "Tuberculosis of lung"), ("U07.1", "COVID-19, virus identified"),
    ("Z00.0", "General medical examination"), ("Z23", "Encounter for immunisation"), ("Z09", "Follow-up examination after treatment")]

# name, category, rate (Rs), gst%
SERVICES = [("Registration fee", "Admin", 50, 0), ("OPD consultation, general", "Consultation", 300, 0), ("OPD consultation, specialist", "Consultation", 600, 0),
    ("Follow-up consultation", "Consultation", 150, 0), ("Dressing", "Procedure", 200, 0), ("Injection administration", "Procedure", 100, 0),
    ("Nebulisation", "Procedure", 250, 0), ("ECG", "Diagnostics", 350, 0), ("X-ray chest", "Imaging", 500, 0), ("Ultrasound abdomen", "Imaging", 1400, 0),
    ("General ward bed, per day", "Inpatient", 1500, 0), ("Private room, per day", "Inpatient", 4500, 0), ("ICU bed, per day", "Inpatient", 8000, 0),
    ("Nursing charges, per day", "Inpatient", 600, 0), ("Doctor visit (IPD)", "Inpatient", 500, 0), ("Ambulance, within city", "Other", 800, 0),
    ("Normal delivery package", "Package", 25000, 0), ("Minor OT procedure", "Procedure", 3500, 0)]

# code, name, sample, rate (Rs), tat hours, [(param, unit, low, high, crit_low, crit_high, ref_text)]
LAB_TESTS = [
    ("CBC", "Complete blood count", "EDTA blood", 400, 4, [("Haemoglobin", "g/dL", 12, 16, 7, 20, ""), ("Total WBC", "x10^3/uL", 4, 11, 2, 30, ""),
        ("Platelets", "x10^3/uL", 150, 450, 50, 1000, ""), ("Neutrophils", "%", 40, 75, None, None, ""), ("Lymphocytes", "%", 20, 45, None, None, "")]),
    ("FBS", "Blood sugar, fasting", "Fluoride plasma", 120, 2, [("Glucose fasting", "mg/dL", 70, 100, 50, 400, "Diabetes >= 126")]),
    ("PPBS", "Blood sugar, post meal", "Fluoride plasma", 120, 2, [("Glucose PP", "mg/dL", 70, 140, 50, 450, "Diabetes >= 200")]),
    ("HBA1C", "HbA1c", "EDTA blood", 550, 24, [("HbA1c", "%", 4, 5.6, None, 14, "Prediabetes 5.7-6.4, diabetes >= 6.5")]),
    ("LIPID", "Lipid profile", "Serum", 650, 24, [("Total cholesterol", "mg/dL", 0, 200, None, None, ""), ("LDL", "mg/dL", 0, 100, None, None, ""),
        ("HDL", "mg/dL", 40, 100, None, None, ""), ("Triglycerides", "mg/dL", 0, 150, None, 1000, "")]),
    ("RFT", "Kidney function", "Serum", 500, 24, [("Creatinine", "mg/dL", 0.6, 1.2, None, 5, ""), ("Urea", "mg/dL", 15, 40, None, 150, ""),
        ("Sodium", "mmol/L", 135, 145, 120, 160, ""), ("Potassium", "mmol/L", 3.5, 5.1, 2.8, 6.2, "")]),
    ("LFT", "Liver function", "Serum", 600, 24, [("SGPT (ALT)", "U/L", 7, 56, None, 1000, ""), ("SGOT (AST)", "U/L", 10, 40, None, 1000, ""),
        ("Total bilirubin", "mg/dL", 0.1, 1.2, None, 15, "")]),
    ("TSH", "Thyroid stimulating hormone", "Serum", 400, 24, [("TSH", "uIU/mL", 0.4, 4.0, None, None, "")]),
    ("URINE", "Urine routine", "Urine", 200, 4, [("Pus cells", "/hpf", 0, 5, None, None, ""), ("Protein", "", None, None, None, None, "Nil"),
        ("Sugar", "", None, None, None, None, "Nil")]),
    ("DENGUE", "Dengue NS1 antigen", "Serum", 700, 6, [("NS1 antigen", "", None, None, None, None, "Negative")]),
    ("MP", "Malaria parasite", "EDTA blood", 250, 4, [("Malaria parasite", "", None, None, None, None, "Not seen")]),
    ("CRP", "C-reactive protein", "Serum", 450, 6, [("CRP", "mg/L", 0, 6, None, None, "")]),
]

# name, diagnosis, icd, advice, [(medicine name, freq, days)], [lab codes], follow-up days
TEMPLATES = [
    ("Viral fever", "Viral fever", "B34.9", "Rest, plenty of fluids. Return if fever lasts over 3 days, rash, bleeding or breathlessness.",
     [("Dolo 650", "1-1-1", 3)], ["CBC"], 3),
    ("Type 2 diabetes review", "Type 2 diabetes mellitus", "E11.9", "Diet control, 30 min walk daily, foot care. Check sugar weekly.",
     [("Glycomet 500", "1-0-1", 30)], ["FBS", "PPBS", "HBA1C"], 30),
    ("Hypertension review", "Essential hypertension", "I10", "Salt under 5 g a day, walk daily, avoid smoking. Check BP weekly.",
     [("Telma 40", "1-0-0", 30)], ["RFT"], 30),
    ("Acute gastritis", "Gastritis", "K29.7", "Small frequent meals. Avoid spicy food, alcohol and painkillers.",
     [("Pan 40", "1-0-0", 14)], [], 14),
    ("Upper respiratory infection", "Acute upper respiratory infection", "J06.9", "Steam inhalation, warm fluids, rest.",
     [("Cetirizine 10", "0-0-1", 5), ("Dolo 650", "SOS", 3)], [], 5),
]

# vaccine, schedule note (National Immunisation Schedule highlights)
VACCINES = ["BCG", "OPV", "Hepatitis B", "Pentavalent", "Rotavirus", "PCV", "IPV", "MR (Measles-Rubella)", "JE", "DPT booster", "Td", "Typhoid conjugate",
            "Influenza", "COVID-19", "Tetanus toxoid (pregnancy)", "HPV"]

TPAS = ["Star Health", "HDFC ERGO", "ICICI Lombard", "Niva Bupa", "Care Health", "Medi Assist TPA", "Paramount TPA", "Ayushman Bharat (PM-JAY)", "CGHS", "ECHS"]

EXPENSE_CATEGORIES = ["Salaries", "Rent", "Electricity", "Medical consumables", "Lab reagents", "Maintenance", "Housekeeping", "Marketing",
                      "Software and internet", "Bank charges", "Doctor payout", "Other"]
