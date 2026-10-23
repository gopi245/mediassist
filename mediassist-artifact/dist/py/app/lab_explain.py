"""Plain-language interpretation of a lab report: what each out-of-range value usually means and an overall
summary, written for the patient. Rule-based so it works offline and instantly; with an Anthropic key the
wording can be rewritten by the model. The doctor reviews it at verification before the patient sees it.
Nothing here is a diagnosis: every text says the doctor decides."""
import json

# parameter -> (what it measures, when high, when low). Keys are matched case-insensitively.
ABOUT = {
    "haemoglobin": ("the oxygen-carrying protein in your blood",
                    "higher than usual; this can happen with dehydration, smoking or some lung and blood conditions",
                    "lower than usual, which is called anaemia; common causes are low iron, low vitamin B12 or folate, heavy periods or blood loss"),
    "total wbc": ("white blood cells, which fight infection",
                  "raised, which most often means the body is fighting an infection or inflammation",
                  "low, which can follow a viral illness, some medicines or a bone marrow problem"),
    "platelets": ("the cells that help blood clot",
                  "raised, which can happen with inflammation, iron deficiency or after an infection",
                  "low; this can happen in dengue and other viral fevers, with some medicines or liver problems, and very low counts can cause bleeding"),
    "neutrophils": ("a type of white cell that fights bacteria",
                    "raised, which usually points to a bacterial infection or inflammation",
                    "low, which can happen after a viral infection or with some medicines"),
    "lymphocytes": ("a type of white cell that fights viruses",
                    "raised, which is common during and after viral infections",
                    "low, which can happen with some infections, stress or medicines"),
    "glucose fasting": ("blood sugar after not eating overnight",
                        "above the normal range; 100-125 is called prediabetes and 126 or more on two occasions suggests diabetes",
                        "low; this can cause shakiness, sweating or confusion and needs attention if you take diabetes medicines"),
    "glucose pp": ("blood sugar about two hours after a meal",
                   "above the normal range; 140-199 suggests prediabetes and 200 or more suggests diabetes",
                   "low after a meal, which is unusual and worth discussing"),
    "hba1c": ("your average blood sugar over the last three months",
              "above the normal range; 5.7-6.4 is prediabetes and 6.5 or more is in the diabetes range, or shows diabetes that needs better control",
              "low, which usually is not a concern"),
    "total cholesterol": ("fat in the blood that can build up in arteries",
                          "higher than recommended, which over years raises the risk of heart disease and stroke; diet, exercise and sometimes medicines help",
                          "low, which is usually fine"),
    "ldl": ("the 'bad' cholesterol",
            "higher than recommended, which raises heart disease risk; the target is lower if you have diabetes or heart disease",
            "low, which is good"),
    "hdl": ("the 'good' cholesterol that protects the heart",
            "high, which is protective",
            "lower than recommended; exercise, stopping smoking and weight loss raise it"),
    "triglycerides": ("another fat in the blood",
                      "raised, often linked to sugar, alcohol, weight and diabetes; very high levels can affect the pancreas",
                      "low, which is fine"),
    "creatinine": ("a waste product that healthy kidneys clear",
                   "raised, which can mean the kidneys are not filtering as well as they should, or that you are dehydrated",
                   "low, which usually just reflects low muscle mass"),
    "urea": ("a waste product cleared by the kidneys",
             "raised, which can happen with dehydration, a high-protein diet, bleeding in the stomach or reduced kidney function",
             "low, which can happen with a low-protein diet or liver problems"),
    "sodium": ("the main salt in your blood",
               "high, usually from not drinking enough water",
               "low, which can happen with vomiting, diarrhoea, some medicines or heart, liver and kidney conditions"),
    "potassium": ("a salt important for the heart and muscles",
                  "high, which can affect the heart rhythm and needs prompt attention, especially with kidney disease or certain blood pressure medicines",
                  "low, which can cause weakness and heart rhythm problems; common after vomiting, diarrhoea or with water tablets"),
    "sgpt (alt)": ("a liver enzyme",
                   "raised, which means some irritation of the liver; common causes are fatty liver, alcohol, viral hepatitis and some medicines",
                   "low, which is fine"),
    "sgot (ast)": ("an enzyme found in the liver and muscles",
                   "raised, which can come from the liver or from muscle; alcohol, fatty liver and hepatitis are common causes",
                   "low, which is fine"),
    "total bilirubin": ("a yellow pigment the liver clears",
                        "raised, which causes yellowing of the eyes or skin (jaundice); causes include hepatitis, bile duct blockage and some blood conditions",
                        "low, which is fine"),
    "tsh": ("the hormone that controls the thyroid gland",
            "raised, which usually means the thyroid is underactive (hypothyroidism), a common and treatable condition",
            "low, which usually means the thyroid is overactive (hyperthyroidism), or that thyroid medicine is more than needed"),
    "pus cells": ("white cells in the urine",
                  "raised, which usually points to a urinary infection",
                  "normal"),
    "protein": ("protein leaking into the urine",
                "present, which can be a sign of kidney stress, high blood pressure, diabetes or, in pregnancy, pre-eclampsia",
                "not present, which is normal"),
    "sugar": ("sugar in the urine",
              "present, which usually means blood sugar is high enough to spill into the urine",
              "not present, which is normal"),
    "ns1 antigen": ("a dengue virus protein",
                    "positive, which means a recent dengue infection; rest, fluids and platelet monitoring matter",
                    "negative, which makes dengue less likely in the first days of fever"),
    "malaria parasite": ("the malaria parasite in blood",
                         "seen, which confirms malaria and needs treatment straight away",
                         "not seen, which makes malaria unlikely"),
    "crp": ("a marker of inflammation",
            "raised, which means there is inflammation or infection somewhere in the body; it does not say where",
            "normal"),
}
FLAG_WORD = {"H": "high", "L": "low", "HH": "critically high", "LL": "critically low", "A": "abnormal", "N": "normal"}


def finding(p):
    """One plain sentence for a parameter row from order_detail (name, value, unit, flag, range)."""
    key = (p.get("name") or "").strip().lower()
    about = ABOUT.get(key)
    fl = p.get("flag") or "N"
    val = f"{p['value']} {p.get('unit') or ''}".strip()
    if fl == "N":
        return f"{p['name']} is {val}, within the normal range" + (f" ({about[0]})." if about else ".")
    if not about:
        word = FLAG_WORD.get(fl, "outside the range")
        return f"{p['name']} is {val}, which is {word} (normal {p.get('range') or '-'}). Your doctor will explain what this means for you."
    what, hi, lo = about
    if fl in ("H", "HH"):
        text = f"{p['name']} ({what}) is {val}, {hi}."
    elif fl in ("L", "LL"):
        text = f"{p['name']} ({what}) is {val}, {lo}."
    else:  # abnormal text result
        text = f"{p['name']} ({what}) is {p['value']}, {hi}."
    if fl in ("HH", "LL"):
        text += " This is a critical value: the doctor has been alerted and will contact you."
    return text


def interpret(detail):
    """Rule-based interpretation for an order_detail dict. Returns {findings, summary, source}."""
    params = [p for t in detail["tests"] for p in t["params"] if p.get("value") not in (None, "")]
    abnormal = [p for p in params if (p.get("flag") or "N") != "N"]
    critical = [p for p in abnormal if p["flag"] in ("HH", "LL")]
    findings = [{"param": p["name"], "value": p["value"], "unit": p.get("unit") or "", "flag": p.get("flag") or "N", "text": finding(p)} for p in abnormal]
    normal_n = len(params) - len(abnormal)
    if not params:
        summary = "No results have been entered yet."
    elif not abnormal:
        summary = f"All {len(params)} results are within the normal range. Please still show this report to your doctor, who will relate it to how you feel."
    else:
        names = ", ".join(p["name"] for p in abnormal)
        summary = (f"{len(abnormal)} of {len(params)} results are outside the normal range: {names}. "
                   + (f"{normal_n} other result{'s are' if normal_n != 1 else ' is'} normal. " if normal_n else "")
                   + ("One or more values are critical, so please contact your doctor today. " if critical else "")
                   + "A single result is not a diagnosis: your doctor will decide what it means together with your symptoms and history.")
    return {"findings": findings, "summary": summary, "source": "rules", "for_patient": True}


AI_SCHEMA = {"type": "object", "properties": {
    "findings": {"type": "array", "items": {"type": "object", "properties": {"param": {"type": "string"}, "text": {"type": "string"}}, "required": ["param", "text"], "additionalProperties": False}},
    "summary": {"type": "string"}}, "required": ["findings", "summary"], "additionalProperties": False}


def ai_prompt(detail, patient):
    rowsq = [f"- {p['name']}: {p['value']} {p.get('unit') or ''} (normal {p.get('range') or '-'}) flag={p.get('flag') or 'N'}"
             for t in detail["tests"] for p in t["params"] if p.get("value") not in (None, "")]
    who = f"{patient.get('age') or '?'}-year-old {patient.get('gender') or 'person'}" + (f" with: {patient['conditions']}" if patient.get("conditions") else "")
    return ("You explain laboratory results to a patient in India in plain, calm English at a 12-year-old's reading level. No diagnosis, no treatment advice, "
            "no medicine names; say what each out-of-range value usually means and that the doctor decides. Keep each finding to one or two sentences. "
            "Only write findings for values whose flag is not N. The summary is 2-3 sentences: how many results are normal, which are out of range, "
            "whether anything is critical (flags HH or LL need contact with the doctor today), and that a single result is not a diagnosis.\n"
            f"Patient: {who}. Tests are from the ordering hospital's lab.\nResults:\n" + "\n".join(rowsq))


def ai_interpret(c, detail, patient):
    """Rewrite with the model when an Anthropic key is configured; raises ApiError with a clear message otherwise."""
    from .core import ApiError, get_settings, need
    key = get_settings(c).get("anthropic_api_key")
    need(key, "AI rewriting is off. Add an Anthropic API key in Admin > Settings; the rule-based explanation is still shown.")
    try:
        import anthropic
    except ImportError:
        raise ApiError(400, "AI rewriting needs the Anthropic SDK on the server: run  pip install anthropic  and restart.")
    client = anthropic.Anthropic(api_key=key)
    try:
        resp = client.beta.messages.create(model="claude-opus-5-5", max_tokens=4000, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                                           output_config={"effort": "low", "format": {"type": "json_schema", "schema": AI_SCHEMA}},
                                           messages=[{"role": "user", "content": ai_prompt(detail, patient)}])
    except anthropic.AuthenticationError:
        raise ApiError(400, "The Anthropic API key was rejected. Check it in Admin > Settings.")
    except anthropic.RateLimitError:
        raise ApiError(429, "The AI service is busy. Try again in a minute.")
    except anthropic.APIStatusError as e:
        raise ApiError(502, f"AI service error ({e.status_code}). Try again later.")
    except anthropic.APIConnectionError:
        raise ApiError(502, "No connection to the AI service. Check the internet connection.")
    text = next((blk.text for blk in resp.content if blk.type == "text"), "")
    try:
        out = json.loads(text)
    except ValueError:
        raise ApiError(502, "The AI gave an unreadable answer. The rule-based explanation is kept.")
    return merge_ai(detail, out)


def merge_ai(detail, out):
    """Keep the rule-based structure (values, flags) and take the model's wording."""
    base = interpret(detail)
    by = {f["param"].strip().lower(): f["text"] for f in out.get("findings", []) if f.get("param") and f.get("text")}
    for f in base["findings"]:
        if by.get(f["param"].lower()):
            f["text"] = str(by[f["param"].lower()])[:600]
    if out.get("summary"):
        base["summary"] = str(out["summary"])[:1200]
    base["source"] = "ai"
    return base
