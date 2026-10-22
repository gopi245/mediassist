"""Clinical decision support: allergy, interaction, condition, dose, renal and pregnancy
checks, plus OPD triage. Rules are deliberately conservative keyword rules. They support
the clinician; they are not a substitute for a licensed drug database or judgement."""
import math
import re
from datetime import date

ALLERGY_CLASSES = {
    "penicillin": ["penicillin", "amoxicillin", "ampicillin", "cloxacillin", "flucloxacillin", "piperacillin"],
    "sulfa": ["sulfamethoxazole", "sulfasalazine", "sulfadiazine", "cotrimoxazole"],
    "nsaid": ["ibuprofen", "diclofenac", "aspirin", "naproxen", "aceclofenac", "mefenamic", "ketorolac"],
    "cephalosporin": ["cefixime", "ceftriaxone", "cefuroxime", "cefpodoxime", "cephalexin", "cefadroxil"],
    "macrolide": ["azithromycin", "clarithromycin", "erythromycin"],
    "quinolone": ["ciprofloxacin", "levofloxacin", "ofloxacin", "moxifloxacin"],
}
CROSS_REACT = {"penicillin": "cephalosporin", "cephalosporin": "penicillin"}
GROUPS = {
    "anticoagulant": ["warfarin", "acenocoumarol", "apixaban", "rivaroxaban", "dabigatran"],
    "antiplatelet": ["aspirin", "clopidogrel", "ticagrelor"], "nsaid": ALLERGY_CLASSES["nsaid"],
    "nitrate": ["nitroglycerin", "isosorbide"], "pde5": ["sildenafil", "tadalafil"],
    "statin": ["simvastatin", "atorvastatin", "lovastatin"], "strong_macrolide": ["clarithromycin", "erythromycin"],
    "acei_arb": ["enalapril", "lisinopril", "ramipril", "telmisartan", "losartan", "olmesartan"],
    "k_sparing": ["spironolactone", "eplerenone", "amiloride"], "ssri": ["fluoxetine", "sertraline", "escitalopram", "paroxetine"],
    "tramadol": ["tramadol"], "methotrexate": ["methotrexate"], "trimethoprim": ["trimethoprim", "sulfamethoxazole", "cotrimoxazole"],
    "digoxin": ["digoxin"], "amiodarone": ["amiodarone"], "theophylline": ["theophylline"], "ciprofloxacin": ["ciprofloxacin"],
    "azole": ["fluconazole", "ketoconazole", "itraconazole"], "metronidazole": ["metronidazole"], "lithium": ["lithium"],
    "diuretic": ["furosemide", "hydrochlorothiazide", "torsemide"], "beta_blocker": ["propranolol", "atenolol", "metoprolol", "carvedilol"],
    "metformin": ["metformin"], "ppi_cyp": ["omeprazole", "esomeprazole"], "clopidogrel": ["clopidogrel"], "insulin": ["insulin"],
    "steroid": ["prednisolone", "dexamethasone", "methylprednisolone", "hydrocortisone"], "paracetamol": ["paracetamol", "acetaminophen"],
    "g6pd_risk": ALLERGY_CLASSES["sulfa"] + ["nitrofurantoin", "primaquine", "dapsone"],
}
INTERACTIONS = [
    ("anticoagulant", "antiplatelet", "high", "major bleeding risk"), ("anticoagulant", "nsaid", "high", "major bleeding risk"),
    ("anticoagulant", "metronidazole", "high", "raises warfarin effect, check INR"), ("anticoagulant", "azole", "high", "raises anticoagulant effect"),
    ("nitrate", "pde5", "high", "severe low blood pressure"), ("statin", "strong_macrolide", "high", "muscle damage risk"),
    ("acei_arb", "k_sparing", "moderate", "high potassium, monitor K+"), ("acei_arb", "nsaid", "moderate", "kidney injury risk"),
    ("ssri", "tramadol", "high", "serotonin syndrome and seizure risk"), ("methotrexate", "trimethoprim", "high", "methotrexate toxicity"),
    ("methotrexate", "nsaid", "moderate", "methotrexate toxicity"), ("digoxin", "amiodarone", "high", "digoxin toxicity"),
    ("theophylline", "ciprofloxacin", "moderate", "theophylline toxicity"), ("lithium", "nsaid", "high", "lithium toxicity"),
    ("lithium", "acei_arb", "high", "lithium toxicity"), ("lithium", "diuretic", "high", "lithium toxicity"),
    ("antiplatelet", "nsaid", "moderate", "stomach bleeding risk"), ("clopidogrel", "ppi_cyp", "moderate", "omeprazole weakens clopidogrel"),
    ("insulin", "beta_blocker", "moderate", "can mask low-sugar warning signs"),
]
# condition keywords (any synonym, matched in the free-text conditions field) -> drug group
KIDNEY_WORDS = ("kidney", "renal", "ckd", "nephro", "dialysis")
HEART_FAILURE_WORDS = ("heart failure", "cardiac failure", "chf", "ccf", "lvf")
LIVER_WORDS = ("liver", "hepat", "cirrhosis", "jaundice")
CONDITION_RULES = [
    (("asthma",), "nsaid", "moderate", "NSAIDs can trigger asthma attacks"),
    (("asthma", "copd", "bronchitis"), "beta_blocker", "high", "non-selective beta blockers cause bronchospasm"),
    (("ulcer", "gastritis", "gi bleed"), "nsaid", "high", "NSAIDs worsen ulcers and bleeding"),
    (KIDNEY_WORDS, "nsaid", "high", "NSAIDs worsen kidney function"), (KIDNEY_WORDS, "metformin", "high", "metformin accumulates in kidney failure"),
    (HEART_FAILURE_WORDS, "nsaid", "high", "NSAIDs worsen heart failure"),
    (LIVER_WORDS, "metronidazole", "moderate", "reduce dose in liver disease"),
    (LIVER_WORDS, "paracetamol", "moderate", "limit paracetamol to 2 g/day in liver disease"),
    (LIVER_WORDS, "statin", "moderate", "statins need liver monitoring in liver disease"),
    (("epilep", "seizure", "fits"), "tramadol", "high", "tramadol lowers the seizure threshold"),
    (("g6pd",), "g6pd_risk", "high", "can cause haemolysis in G6PD deficiency"),
    (("diabet", "dm"), "steroid", "moderate", "steroids raise blood sugar; monitor"),
]
STOP_WORDS = {"acid", "sodium", "potassium", "hydrochloride", "hcl", "sulphate", "sulfate", "and", "with", "plus", "calcium", "maleate", "succinate"}


def ingredients(m):
    """Set of ingredient words in the generic name: 'tramadol paracetamol' -> {tramadol, paracetamol}."""
    return {w for w in re.split(r"[\s+/,]+", (m.get("generic") or "").lower()) if len(w) > 3 and w not in STOP_WORDS}


def matches(cond, words):
    return any(w in cond for w in words)


def egfr(creatinine, age, weight, gender):
    """Cockcroft-Gault creatinine clearance, mL/min. None when any input is missing."""
    if not creatinine or not age or not weight or creatinine <= 0:
        return None
    v = (140 - age) * weight / (72 * creatinine)
    return round(v * (0.85 if (gender or "").lower().startswith("f") else 1), 0)


def med_text(m):
    return f"{m.get('generic') or ''} {m['name']}".lower()


def groups_of(m):
    t = med_text(m)
    return {g for g, words in GROUPS.items() if any(w in t for w in words)}


def age_of(p):
    if p.get("dob"):
        try:
            d = date.fromisoformat(p["dob"])
            t = date.today()
            return t.year - d.year - ((t.month, t.day) < (d.month, d.day))
        except ValueError:
            pass
    return p.get("age")


def is_pregnant(p):
    if p.get("lmp"):
        try:
            return 0 <= (date.today() - date.fromisoformat(p["lmp"])).days <= 300
        except ValueError:
            pass
    return "pregnan" in (p.get("conditions") or "").lower()


def per_day(freq):
    """Administrations per day: '1-0-1' -> 2, 'TDS' -> 3, 'Q6H' / 'every 6 hours' / '6 hourly' -> 4, 'SOS' -> 0."""
    f = (freq or "").strip().upper()
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", f)]
    if "-" in f and nums:
        return sum(nums)
    m = re.match(r"^(?:Q(\d+)H|(?:EVERY|EV|E)\s*(\d+)\s*(?:H|HR|HRS|HOUR|HOURS|HOURLY)|(\d+)\s*(?:H|HR|HRS|HOURLY|HOUR|HOURS))$", f)
    if m:
        h = float(next(x for x in m.groups() if x))
        return 24 / h if h else 1
    return {"OD": 1, "ONCE": 1, "DAILY": 1, "HS": 1, "BD": 2, "BID": 2, "TWICE": 2, "TDS": 3, "TID": 3, "THRICE": 3, "QID": 4, "QDS": 4,
            "SOS": 0, "PRN": 0, "STAT": 1, "WEEKLY": 1 / 7, "ALTERNATE": 0.5}.get(f, 1)


DOSE_UNITS = {"mg": "mg", "g": "g", "gm": "g", "mcg": "mcg", "ug": "mcg", "ml": "ml", "tab": "", "tabs": "", "tablet": "", "tablets": "", "cap": "", "caps": "",
              "capsule": "", "drop": "", "drops": "", "puff": "", "puffs": "", "unit": "", "units": "", "iu": ""}


def dose_parse(dose):
    """'1', '1/2', '2 tab' -> (units, ''); '500 mg' -> (500, 'mg'); '5 ml' -> (5, 'ml'); '1 g' -> (1000, 'mg').
    Units of strength (tablets, capsules) carry ''; weights are normalised to mg."""
    s = str(dose or "").strip().lower()
    m = re.match(r"^(\d+)\s*/\s*(\d+)\s*([a-z]*)", s)
    if m:
        n, unit = int(m.group(1)) / int(m.group(2)), m.group(3)
    else:
        m = re.match(r"^(\d+(?:\.\d+)?)\s*([a-z]*)", s)
        if not m:
            return 1.0, ""
        n, unit = float(m.group(1)), m.group(2)
    unit = DOSE_UNITS.get(unit, "")
    if unit == "g":
        return n * 1000, "mg"
    if unit == "mcg":
        return n / 1000, "mg"
    return n, unit


def dose_units(dose):
    """Units of strength per administration (tablets etc.); 1 when the dose is given as a weight or volume."""
    n, unit = dose_parse(dose)
    return n if unit == "" else 1.0


def daily_mg(m, dose, freq):
    """Total mg/day, or None when it cannot be worked out (dose in ml, or in units with no strength)."""
    n, unit = dose_parse(dose)
    per = per_day(freq)
    if unit == "mg":
        return n * per
    if unit == "" and m.get("strength_mg"):
        return m["strength_mg"] * n * per
    return None


def safety_check(patient, new_items, current_meds=(), creatinine=None):
    """new_items: list of dicts {med: medicine row, freq, dose, days}. Returns warnings sorted high first."""
    out = []

    def add(sev, text):
        w = {"severity": sev, "text": text}
        if w not in out:
            out.append(w)
    meds = [i["med"] for i in new_items]
    if patient:
        allergies = [a.strip().lower() for a in re.split(r"[,;/]", patient.get("allergies") or "") if a.strip()]
        cond = (patient.get("conditions") or "").lower()
        age, wt, preg = age_of(patient), patient.get("weight"), is_pregnant(patient)
        kidney = matches(cond, KIDNEY_WORDS)
        crcl = egfr(creatinine, age, wt, patient.get("gender"))
        for it in new_items:
            m, t = it["med"], med_text(it["med"])
            for a in allergies:
                key = next((k for k in ALLERGY_CLASSES if k in a or a in k), None)
                members = ALLERGY_CLASSES.get(key, [])
                if a in t or any(x in t for x in members):
                    add("high", f"Allergy: patient is allergic to {a}. {m['name']} contains {m.get('generic')}.")
                elif key in CROSS_REACT and any(x in t for x in ALLERGY_CLASSES[CROSS_REACT[key]]):
                    add("moderate", f"{m['name']}: possible cross-reaction with the {a} allergy.")
            for words, grp, sev, msg in CONDITION_RULES:
                if matches(cond, words) and grp in groups_of(m):
                    add(sev, f"{m['name']}: {msg} (patient record: {patient.get('conditions')}).")
            if preg and m.get("pregnancy_avoid"):
                add("high", f"{m['name']}: avoid in pregnancy. Choose a safer alternative.")
            if age is not None and age < 16 and "aspirin" in t:
                add("high", f"{m['name']}: aspirin in children risks Reye's syndrome.")
            if m.get("renal_caution") and (kidney or (crcl is not None and crcl < 60) or (crcl is None and creatinine and creatinine > 1.5)):
                why = f" (creatinine {creatinine:g}, est. clearance {crcl:g} mL/min)." if crcl is not None else f" (creatinine {creatinine:g})." if creatinine else "."
                add("moderate", f"{m['name']}: reduce dose or avoid in kidney impairment" + why)
            child = age is not None and age < 16 and m.get("ped_mg_per_kg_day")
            if it.get("freq") and per_day(it.get("freq")):
                daily = daily_mg(m, it.get("dose"), it.get("freq"))
                if daily is None:
                    if child and (m.get("strength_mg") or dose_parse(it.get("dose"))[1] == "ml"):
                        add("moderate", f"{m['name']}: enter the dose in mg (e.g. 250 mg) so the child's dose can be checked.")
                elif child:
                    if wt:
                        lim = m["ped_mg_per_kg_day"] * wt
                        if m.get("max_daily_mg"):
                            lim = min(lim, m["max_daily_mg"])
                        if daily > lim * 1.05:
                            add("high", f"{m['name']}: {daily:g} mg/day is above the child limit of {lim:g} mg/day "
                                        f"({m['ped_mg_per_kg_day']:g} mg/kg/day for {wt:g} kg).")
                    else:
                        add("moderate", f"{m['name']}: child under 16. Record the weight so the dose can be checked.")
                elif m.get("max_daily_mg") and daily > m["max_daily_mg"] * 1.0001:
                    add("high", f"{m['name']}: {daily:g} mg/day is above the usual maximum of {m['max_daily_mg']:g} mg/day.")
    pool = [(m, True) for m in meds] + [(m, False) for m in current_meds]
    for i in range(len(pool)):
        for j in range(i + 1, len(pool)):
            (a, an), (b, bn) = pool[i], pool[j]
            if not (an or bn) or a["id"] == b["id"]:
                continue
            src = "" if (an and bn) else " (already taking)"
            shared = ingredients(a) & ingredients(b)
            if shared:
                add("moderate", f"Duplicate: {a['name']} and {b['name']} both contain {', '.join(sorted(shared))}{src}.")
            ga, gb = groups_of(a), groups_of(b)
            for x, y, sev, msg in INTERACTIONS:
                if (x in ga and y in gb) or (y in ga and x in gb):
                    add(sev, f"Interaction: {a['name']} + {b['name']}{src}: {msg}.")
    return sorted(out, key=lambda w: w["severity"] != "high")


def triage(v):
    s, why = 0, []
    sy = (v.get("complaint") or "").lower()
    num = lambda k: v.get(k) if isinstance(v.get(k), (int, float)) else None
    spo2, pulse, sbp, temp, sugar = num("spo2"), num("pulse"), num("bp_sys"), num("temp"), num("sugar")
    if spo2 is not None and spo2 < 92: s += 4; why.append(f"SpO2 {spo2}%")
    if pulse is not None:
        if pulse > 120 or pulse < 45: s += 3; why.append(f"pulse {pulse}")
        elif pulse > 100: s += 1; why.append("fast pulse")
    if sbp is not None:
        if sbp > 180 or sbp < 90: s += 3; why.append(f"BP {sbp}")
        elif sbp > 160: s += 2; why.append(f"high BP {sbp}")
    if temp is not None:
        if temp >= 39.5: s += 2; why.append("high fever")
        elif temp >= 38: s += 1; why.append("fever")
    if sugar is not None and (sugar < 60 or sugar > 400): s += 4; why.append(f"blood sugar {sugar:g}")
    for k in ("chest pain", "breathless", "unconscious", "seizure", "bleeding", "stroke", "slurred", "severe"):
        if k in sy: s += 4; why.append(k)
    for k in ("vomit", "fracture", "abdominal pain", "dizzy", "sweating", "pregnan"):
        if k in sy: s += 1; why.append(k)
    return ("critical" if s >= 6 else "urgent" if s >= 3 else "normal"), ", ".join(why)


def qty_for(med, freq, days, dose=None):
    if med.get("form") in ("Syrup", "Injection", "Cream", "Drops"):
        return 1
    return max(1, math.ceil(per_day(freq) * dose_units(dose) * (days or 1)))
