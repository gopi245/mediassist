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
CONDITION_RULES = [
    ("asthma", "nsaid", "moderate", "NSAIDs can trigger asthma attacks"), ("asthma", "beta_blocker", "high", "non-selective beta blockers cause bronchospasm"),
    ("ulcer", "nsaid", "high", "NSAIDs worsen ulcers and bleeding"), ("kidney", "nsaid", "high", "NSAIDs worsen kidney function"),
    ("ckd", "nsaid", "high", "NSAIDs worsen kidney function"), ("heart failure", "nsaid", "high", "NSAIDs worsen heart failure"),
    ("liver", "metronidazole", "moderate", "reduce dose in liver disease"),
]


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
    f = (freq or "").strip().upper()
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", f)]
    if "-" in f and nums:
        return sum(nums)
    return {"OD": 1, "HS": 1, "BD": 2, "BID": 2, "TDS": 3, "TID": 3, "QID": 4, "QDS": 4, "SOS": 0, "STAT": 1}.get(f, 1)


def dose_units(dose):
    """'1', '1/2', '0.5', '2 tab' -> units per administration (default 1)."""
    s = str(dose or "").strip()
    m = re.match(r"^(\d+)\s*/\s*(\d+)", s)
    if m:
        return int(m.group(1)) / int(m.group(2))
    m = re.match(r"^(\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else 1.0


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
        for it in new_items:
            m, t = it["med"], med_text(it["med"])
            for a in allergies:
                key = next((k for k in ALLERGY_CLASSES if k in a or a in k), None)
                members = ALLERGY_CLASSES.get(key, [])
                if a in t or any(x in t for x in members):
                    add("high", f"Allergy: patient is allergic to {a}. {m['name']} contains {m.get('generic')}.")
                elif key in CROSS_REACT and any(x in t for x in ALLERGY_CLASSES[CROSS_REACT[key]]):
                    add("moderate", f"{m['name']}: possible cross-reaction with the {a} allergy.")
            for c, grp, sev, msg in CONDITION_RULES:
                if c in cond and grp in groups_of(m):
                    add(sev, f"{m['name']}: {msg} (patient record: {patient.get('conditions')}).")
            if preg and m.get("pregnancy_avoid"):
                add("high", f"{m['name']}: avoid in pregnancy. Choose a safer alternative.")
            if age is not None and age < 16 and "aspirin" in t:
                add("high", f"{m['name']}: aspirin in children risks Reye's syndrome.")
            if m.get("renal_caution") and (("kidney" in cond or "ckd" in cond) or (creatinine and creatinine > 1.5)):
                add("moderate", f"{m['name']}: reduce dose or avoid in kidney impairment" + (f" (creatinine {creatinine})." if creatinine else "."))
            # dose checks need strength
            sm = m.get("strength_mg")
            if sm and it.get("freq"):
                daily = sm * dose_units(it.get("dose")) * per_day(it.get("freq"))
                if age is not None and age < 12 and m.get("ped_mg_per_kg_day"):
                    if wt:
                        lim = m["ped_mg_per_kg_day"] * wt
                        if daily > lim * 1.05:
                            add("high", f"{m['name']}: {daily:g} mg/day is above the child limit of {lim:g} mg/day "
                                        f"({m['ped_mg_per_kg_day']:g} mg/kg/day for {wt:g} kg).")
                    else:
                        add("moderate", f"{m['name']}: child under 12. Record the weight so the dose can be checked.")
                elif m.get("max_daily_mg") and daily > m["max_daily_mg"] * 1.0001:
                    add("high", f"{m['name']}: {daily:g} mg/day is above the usual maximum of {m['max_daily_mg']:g} mg/day.")
    pool = [(m, True) for m in meds] + [(m, False) for m in current_meds]
    for i in range(len(pool)):
        for j in range(i + 1, len(pool)):
            (a, an), (b, bn) = pool[i], pool[j]
            if not (an or bn) or a["id"] == b["id"]:
                continue
            src = "" if (an and bn) else " (already taking)"
            ka = (a.get("generic") or "").lower().split()[:1]
            if ka and ka == (b.get("generic") or "").lower().split()[:1]:
                add("moderate", f"Duplicate: {a['name']} and {b['name']} both contain {ka[0]}{src}.")
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
