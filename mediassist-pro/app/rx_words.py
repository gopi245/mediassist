"""The prescription in words a patient can follow: 'Dolo 650: 1 tablet morning, 1 tablet night, after food, for 5 days',
in English, Hindi, Telugu or Tamil. Turns the doctor's shorthand (1-0-1, BD, TDS, Q6H, SOS...) into times of day."""
import re

PHRASES = {
    "en": {"tablet": "tablet", "tablets": "tablets", "unit": "dose", "units": "doses", "ml": "ml", "morning": "morning", "afternoon": "afternoon", "evening": "evening", "night": "night",
           "bedtime": "at bedtime", "sos": "only when needed", "stat": "once, now", "every": "every {h} hours", "weekly": "once a week", "alt": "on alternate days",
           "for_days": "for {n} day", "for_days_pl": "for {n} days", "and": ", ", "followup": "Come back on {d}", "header": "Your prescription from {doc}, {branch}",
           "tests": "Tests advised: {t}", "advice": "Advice: {a}", "keep": "Keep this message. Show it at the pharmacy and at your next visit."},
    "hi": {"tablet": "गोली", "tablets": "गोलियाँ", "unit": "खुराक", "units": "खुराक", "ml": "मिली", "morning": "सुबह", "afternoon": "दोपहर", "evening": "शाम", "night": "रात",
           "bedtime": "सोते समय", "sos": "केवल ज़रूरत पड़ने पर", "stat": "एक बार, अभी", "every": "हर {h} घंटे", "weekly": "हफ़्ते में एक बार", "alt": "एक दिन छोड़कर",
           "for_days": "{n} दिन तक", "for_days_pl": "{n} दिन तक", "and": ", ", "followup": "{d} को दोबारा आएँ", "header": "{branch} से {doc} की आपकी दवा-पर्ची",
           "tests": "जाँच: {t}", "advice": "सलाह: {a}", "keep": "यह संदेश सँभाल कर रखें। दवा की दुकान और अगली बार दिखाएँ।"},
    "te": {"tablet": "మాత్ర", "tablets": "మాత్రలు", "unit": "మోతాదు", "units": "మోతాదులు", "ml": "మి.లీ", "morning": "ఉదయం", "afternoon": "మధ్యాహ్నం", "evening": "సాయంత్రం", "night": "రాత్రి",
           "bedtime": "పడుకునే ముందు", "sos": "అవసరమైనప్పుడు మాత్రమే", "stat": "ఒకసారి, ఇప్పుడే", "every": "ప్రతి {h} గంటలకు", "weekly": "వారానికి ఒకసారి", "alt": "రోజు విడిచి రోజు",
           "for_days": "{n} రోజులు", "for_days_pl": "{n} రోజులు", "and": ", ", "followup": "{d}న మళ్ళీ రండి", "header": "{branch}, {doc} ఇచ్చిన మీ మందుల చీటీ",
           "tests": "పరీక్షలు: {t}", "advice": "సలహా: {a}", "keep": "ఈ సందేశాన్ని భద్రపరచండి. మందుల దుకాణంలో, తదుపరి సందర్శనలో చూపించండి."},
    "ta": {"tablet": "மாத்திரை", "tablets": "மாத்திரைகள்", "unit": "அளவு", "units": "அளவுகள்", "ml": "மி.லி", "morning": "காலை", "afternoon": "மதியம்", "evening": "மாலை", "night": "இரவு",
           "bedtime": "தூங்கும் முன்", "sos": "தேவைப்படும்போது மட்டும்", "stat": "ஒரு முறை, இப்போதே", "every": "ஒவ்வொரு {h} மணி நேரத்திற்கும்", "weekly": "வாரம் ஒரு முறை", "alt": "ஒரு நாள் விட்டு ஒரு நாள்",
           "for_days": "{n} நாட்களுக்கு", "for_days_pl": "{n} நாட்களுக்கு", "and": ", ", "followup": "{d} அன்று மீண்டும் வரவும்", "header": "{branch}, {doc} அளித்த உங்கள் மருந்துச் சீட்டு",
           "tests": "பரிசோதனைகள்: {t}", "advice": "அறிவுரை: {a}", "keep": "இந்தச் செய்தியை வைத்திருங்கள். மருந்தகத்திலும் அடுத்த வருகையிலும் காட்டவும்."},
}
SLOT3 = ("morning", "afternoon", "night")
SLOT4 = ("morning", "afternoon", "evening", "night")


def fmt_n(n):
    return f"{n:g}" if isinstance(n, float) else str(n)


def dose_phrase(count, dose, form, P):
    """'1 tablet' / '2 tablets' / '5 ml' / '1 dose', from the slot count and the dose text."""
    d = (dose or "").strip().lower()
    m = re.match(r"^(\d+/\d+|\d+(?:\.\d+)?)\s*(ml|mg|g|mcg|drops?|puffs?|tsp)?", d)
    if m and m.group(2):  # a measured dose: say it as written
        return d
    per = 1.0
    if m:
        a = m.group(1)
        per = float(a.split("/")[0]) / float(a.split("/")[1]) if "/" in a else float(a)
    n = per * count
    text = "½" if n == 0.5 else "1½" if n == 1.5 else fmt_n(n)
    is_tab = (form or "").lower() in ("tablet", "capsule", "")
    word = (P["tablet"] if n <= 1 else P["tablets"]) if is_tab else (P["unit"] if n <= 1 else P["units"])
    return f"{text} {word}"


def schedule(freq, dose, form, lang="en"):
    """'1-0-1' -> 'morning 1 tablet, night 1 tablet'; 'TDS' -> three times; 'Q6H' -> 'every 6 hours'; 'SOS' -> 'only when needed'."""
    P = PHRASES.get(lang or "en", PHRASES["en"])
    f = (freq or "").strip().upper()
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", f)]
    if "-" in f and nums:
        slots = SLOT4 if len(nums) == 4 else SLOT3
        parts = [f"{P[s]} {dose_phrase(n, dose, form, P)}" for s, n in zip(slots, nums) if n]
        return P["and"].join(parts) if parts else P["sos"]
    m = re.match(r"^(?:Q(\d+)H|(?:EVERY|EV|E)\s*(\d+)\s*(?:H|HR|HRS|HOUR|HOURS|HOURLY)|(\d+)\s*(?:H|HR|HRS|HOURLY|HOUR|HOURS))$", f)
    if m:
        h = next(x for x in m.groups() if x)
        return f"{dose_phrase(1, dose, form, P)} {P['every'].format(h=h)}"
    table = {"OD": ("morning",), "ONCE": ("morning",), "DAILY": ("morning",), "BD": ("morning", "night"), "BID": ("morning", "night"), "TWICE": ("morning", "night"),
             "TDS": SLOT3, "TID": SLOT3, "THRICE": SLOT3, "QID": SLOT4, "QDS": SLOT4}
    if f in table:
        return P["and"].join(f"{P[s]} {dose_phrase(1, dose, form, P)}" for s in table[f])
    if f == "HS":
        return f"{P['bedtime']} {dose_phrase(1, dose, form, P)}"
    if f in ("SOS", "PRN"):
        return f"{dose_phrase(1, dose, form, P)} {P['sos']}"
    if f == "STAT":
        return f"{dose_phrase(1, dose, form, P)} {P['stat']}"
    if f == "WEEKLY":
        return f"{dose_phrase(1, dose, form, P)} {P['weekly']}"
    if f == "ALTERNATE":
        return f"{dose_phrase(1, dose, form, P)} {P['alt']}"
    return f"{dose_phrase(1, dose, form, P)} {freq}".strip()


def how_to_take(item, lang="en"):
    """One line for one medicine: schedule, instructions as typed, duration."""
    P = PHRASES.get(lang or "en", PHRASES["en"])
    bits = [schedule(item.get("freq"), item.get("dose"), item.get("form"), lang)]
    if item.get("instructions"):
        bits.append(item["instructions"])
    days = item.get("days")
    if days and (item.get("freq") or "").strip().upper() not in ("SOS", "PRN", "STAT"):
        bits.append((P["for_days"] if days == 1 else P["for_days_pl"]).format(n=days))
    return ", ".join(bits)


def rx_message(items, lang, doctor, branch, followup=None, tests=(), advice=None):
    """The whole prescription as a WhatsApp message in the patient's language."""
    P = PHRASES.get(lang or "en", PHRASES["en"])
    lines = [P["header"].format(doc=doctor, branch=branch), ""]
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. {it['name']}: {how_to_take(it, lang)}")
    if not items:
        lines.append("-")
    if tests:
        lines += ["", P["tests"].format(t=", ".join(tests))]
    if advice:
        lines += ["", P["advice"].format(a=advice)]
    if followup:
        lines += ["", P["followup"].format(d=followup)]
    lines += ["", P["keep"]]
    return "\n".join(lines)
