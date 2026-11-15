"""Synthetic Hinglish OPD consultation generator with exact gold labels.

Why synthetic: real consult audio needs ethics approval and consent, which
is the next phase. The generator produces *scripts* that the team (and
consenting volunteers) can read aloud as role-plays, so the same gold
labels carry over to real audio.

Each consult is built from structured facts first, then rendered into
Hinglish dialogue, so the gold annotation is exactly what was rendered.
Patients have 1-3 visits so that longitudinal memory can be tested
(allergies told at visit 1, conflicting drug prescribed at visit 2).
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

SX_SURFACE = {  # surface forms used when *rendering* (subset of lexicon, mixed Hindi/English)
    "fever": ["bukhar", "fever", "bukhaar"], "cough": ["khansi", "cough", "khaansi"],
    "sore_throat": ["gale mein dard", "sore throat", "gala kharab"], "runny_nose": ["zukaam", "naak beh rahi", "runny nose"],
    "headache": ["sar dard", "sir mein dard", "headache"], "body_ache": ["badan dard", "body pain"],
    "vomiting": ["ulti", "vomiting"], "nausea": ["ji machlana", "nausea"], "diarrhoea": ["dast", "loose motion"],
    "abdominal_pain": ["pet mein dard", "pet dard", "stomach pain"], "breathlessness": ["saans phoolna", "saans lene mein dikkat"],
    "fatigue": ["kamzori", "thakan", "weakness"], "dizziness": ["chakkar"], "dysuria": ["peshab mein jalan", "burning urine"],
    "rash": ["daane", "rash"], "loss_of_appetite": ["bhookh kam"], "chills": ["thand lagna", "kapkapi"],
    "excessive_thirst": ["zyada pyaas"], "heartburn": ["seene mein jalan", "acidity", "khatti dakar"], "chest_pain": ["seene mein dard", "chest pain"],
}
COND_SURFACE = {
    "t2dm": ["sugar", "diabetes"], "hypertension": ["bp ki problem", "high bp"], "asthma": ["asthma", "dama"],
    "hypothyroidism": ["thyroid"], "viral_urti": ["viral urti", "upper respiratory infection"], "viral_fever": ["viral fever", "viral infection"],
    "gastroenteritis": ["gastroenteritis", "pet ka infection"], "uti": ["urine infection", "uti"], "gastritis": ["gastritis"],
    "dengue": ["dengue"], "typhoid": ["typhoid"], "migraine": ["migraine"], "pharyngitis": ["gale ka infection", "pharyngitis"],
}
DRUG_SURFACE = {
    "paracetamol": ["paracetamol", "dolo", "crocin"], "cetirizine": ["cetirizine", "okacet"], "azithromycin": ["azithromycin", "azithral"],
    "amoxicillin": ["amoxicillin", "mox"], "amoxiclav": ["augmentin"], "ors": ["ors", "electral"], "ondansetron": ["ondansetron", "ondem"],
    "nitrofurantoin": ["nitrofurantoin", "niftran"], "cotrimoxazole": ["septran"], "metformin": ["metformin", "glycomet"],
    "glimepiride": ["glimepiride"], "amlodipine": ["amlodipine", "amlokind"], "telmisartan": ["telmisartan", "telma"],
    "pantoprazole": ["pantoprazole", "pantocid"], "domperidone": ["domperidone"], "salbutamol": ["asthalin", "salbutamol"],
    "montelukast": ["montelukast", "montair"], "ibuprofen": ["ibuprofen", "brufen"], "diclofenac": ["diclofenac"],
    "levothyroxine": ["thyronorm", "levothyroxine"], "ciprofloxacin": ["ciprofloxacin"],
}
NUMW = {1: "ek", 2: "do", 3: "teen", 4: "chaar", 5: "paanch", 7: "saat", 10: "das"}
DUR_CHOICES = [("kal se", 1), ("do din se", 2), ("teen din se", 3), ("chaar din se", 4), ("paanch din se", 5), ("ek hafte se", 7)]
FREQ_PHRASE = {"OD": ["din mein ek baar", "roz ek baar"], "BD": ["din mein do baar", "subah shaam"],
               "TDS": ["din mein teen baar", "subah dopahar shaam"], "HS": ["raat ko sone se pehle"], "SOS": ["zarurat pade toh"]}
ALLERGY_SURFACE = {"penicillin_allergy": ["penicillin"], "sulfonamide_allergy": ["sulfa", "septran"], "aspirin_allergy": ["aspirin", "disprin"]}
CONFLICT_DRUG = {"penicillin_allergy": ("amoxicillin", 500, "mg", "TDS", 5), "sulfonamide_allergy": ("cotrimoxazole", None, None, "BD", 5),
                 "aspirin_allergy": ("ibuprofen", 400, "mg", "TDS", 3)}
CONFLICT_CLASS = {"penicillin_allergy": {"amoxicillin", "amoxiclav"}, "sulfonamide_allergy": {"cotrimoxazole"},
                  "aspirin_allergy": {"ibuprofen", "diclofenac", "aspirin"}}


@dataclass
class Rx:
    drug_id: str
    dose_value: float | None
    dose_unit: str | None
    frequency: str | None
    duration_days: float | None


@dataclass
class Scenario:
    name: str
    symptoms: list[str]
    optional_symptoms: list[str]
    negatives: list[str]
    dx: str
    meds: list[Rx]
    vitals: list[str]
    history: list[str] = field(default_factory=list)


SCENARIOS = [
    Scenario("viral_urti", ["cough", "runny_nose"], ["fever", "sore_throat", "headache"], ["breathlessness", "vomiting"], "viral_urti",
             [Rx("paracetamol", 650, "mg", "TDS", 3), Rx("cetirizine", 10, "mg", "HS", 5)], ["temperature"]),
    Scenario("viral_fever", ["fever", "body_ache"], ["headache", "fatigue", "chills"], ["cough", "vomiting"], "viral_fever",
             [Rx("paracetamol", 650, "mg", "TDS", 3)], ["temperature", "pulse"]),
    Scenario("gastroenteritis", ["diarrhoea", "vomiting"], ["abdominal_pain", "fever"], ["chest_pain"], "gastroenteritis",
             [Rx("ors", None, None, None, None), Rx("ondansetron", 4, "mg", "BD", 3)], ["pulse"]),
    Scenario("uti", ["dysuria"], ["fever", "abdominal_pain"], ["vomiting"], "uti",
             [Rx("nitrofurantoin", 100, "mg", "BD", 5), Rx("paracetamol", 650, "mg", "SOS", None)], ["temperature"]),
    Scenario("gastritis", ["heartburn", "abdominal_pain"], ["nausea"], ["vomiting", "fever"], "gastritis",
             [Rx("pantoprazole", 40, "mg", "OD", 14)], []),
    Scenario("dengue", ["fever", "body_ache"], ["rash", "headache"], ["cough"], "dengue",
             [Rx("paracetamol", 650, "mg", "TDS", 5)], ["temperature", "pulse"]),
    Scenario("typhoid", ["fever", "loss_of_appetite"], ["abdominal_pain", "fatigue"], ["cough"], "typhoid",
             [Rx("azithromycin", 500, "mg", "OD", 7), Rx("paracetamol", 650, "mg", "SOS", None)], ["temperature"]),
    Scenario("pharyngitis", ["sore_throat", "fever"], ["headache"], ["cough", "runny_nose"], "pharyngitis",
             [Rx("amoxicillin", 500, "mg", "TDS", 5)], ["temperature"]),
    Scenario("migraine", ["headache", "nausea"], ["dizziness"], ["fever", "vomiting"], "migraine",
             [Rx("paracetamol", 650, "mg", "SOS", None), Rx("domperidone", 10, "mg", "SOS", None)], ["bp"]),
    Scenario("asthma", ["breathlessness", "cough"], [], ["fever", "chest_pain"], "asthma",
             [Rx("salbutamol", 2, "puff", "SOS", None), Rx("montelukast", 10, "mg", "HS", 14)], ["spo2"], ["asthma"]),
    Scenario("t2dm", ["fatigue", "excessive_thirst"], [], ["chest_pain"], "t2dm",
             [Rx("metformin", 500, "mg", "BD", 30), Rx("glimepiride", 1, "mg", "OD", 30)], ["fasting_glucose"], ["t2dm"]),
    Scenario("hypertension", ["headache", "dizziness"], [], ["chest_pain", "breathlessness"], "hypertension",
             [Rx("amlodipine", 5, "mg", "OD", 30)], ["bp"], ["hypertension"]),
]
SC = {s.name: s for s in SCENARIOS}


def _vital(name: str, rng: random.Random, dx: str) -> tuple[str, dict]:
    if name == "temperature":
        t = rng.choice([100, 101, 102, 100.5]) if dx in {"viral_fever", "dengue", "typhoid", "uti", "pharyngitis"} else rng.choice([98.6, 99, 100])
        return f"Temperature {t:g} hai.", {"name": "temperature", "value": t, "value2": None}
    if name == "pulse":
        p = rng.choice([88, 96, 104, 110])
        return f"Pulse {p} hai.", {"name": "pulse", "value": p, "value2": None}
    if name == "bp":
        s, d = (rng.choice([150, 156, 162]), rng.choice([94, 96, 100])) if dx == "hypertension" else (rng.choice([118, 124, 130]), rng.choice([78, 80, 84]))
        return f"BP {s} by {d} hai.", {"name": "bp", "value": s, "value2": d}
    if name == "spo2":
        v = rng.choice([94, 95, 96])
        return f"Oxygen {v} percent hai.", {"name": "spo2", "value": v, "value2": None}
    if name == "fasting_glucose":
        g = rng.choice([156, 168, 182, 210])
        return f"Fasting sugar {g} aaya hai.", {"name": "fasting_glucose", "value": g, "value2": None}
    raise KeyError(name)


def _rx_sentence(rx: Rx, rng: random.Random) -> str:
    surf = rng.choice(DRUG_SURFACE[rx.drug_id])
    if rx.drug_id == "ors":
        return f"{surf.upper() if surf == 'ors' else surf.capitalize()} ka ghol har dast ke baad pijiye."
    if rx.dose_unit == "puff":
        return f"{surf.capitalize()} inhaler {NUMW[int(rx.dose_value)]} puff {FREQ_PHRASE[rx.frequency][0]} lijiye."
    dose = ""
    if rx.dose_value:
        dose = f" {rx.dose_value:g}" if surf in {"dolo", "crocin"} else f" {rx.dose_value:g} mg"
    freq = rng.choice(FREQ_PHRASE[rx.frequency]) if rx.frequency else ""
    dur = ""
    if rx.duration_days:
        d = int(rx.duration_days)
        dur = {30: "ek mahine ke liye", 14: "do hafte ke liye", 7: "saat din ke liye"}.get(d, f"{NUMW.get(d, str(d))} din ke liye")
    tmpl = rng.choice(["{s}{dose} {freq} lijiye, {dur}.", "Main {s}{dose} de raha hoon, {freq}, {dur}.", "Tablet {s}{dose} {freq} lena hai, {dur}."])
    out = tmpl.format(s=surf.capitalize() if surf[0].isalpha() else surf, dose=dose, freq=freq, dur=dur)
    return out.replace(", .", ".").replace(" ,", ",").replace("  ", " ")


def make_consult(rng: random.Random, pid: str, visit_no: int, vdate: date, scenario: Scenario, profile: dict,
                 inappropriate_abx: bool = False, conflict_allergy: str | None = None, mention_allergy: bool = True) -> dict:
    turns: list[dict] = []
    D = lambda t: turns.append({"speaker": "doctor", "text": t})  # noqa: E731
    P = lambda t: turns.append({"speaker": "patient", "text": t})  # noqa: E731
    gold = {"symptoms": [], "history": [], "diagnoses": [scenario.dx], "allergies": [], "medications": [], "vitals": [],
            "follow_up_days": None, "expected_flags": []}

    D(rng.choice(["Namaste, aaiye baithiye. Batayiye kya taklif hai?", "Haan ji, boliye kya problem hai?", "Achha, aaj kya hua? Batayiye."]
                 if visit_no == 1 else ["Namaste, aap phir aaye. Ab kya taklif hai?", "Haan ji, pichli baar ke baad ab kya problem hai?"]))

    sxs = list(scenario.symptoms) + [s for s in scenario.optional_symptoms if rng.random() < 0.5]
    rng.shuffle(sxs)
    chronic = scenario.name in {"t2dm", "hypertension"}
    first = True
    for s in sxs:
        if chronic:
            dur_txt, dur = rng.choice([("ek hafte se", 7), ("do hafte se", 14), ("kuch dino se", None)])
        else:
            dur_txt, dur = rng.choice(DUR_CHOICES)
        surf = rng.choice(SX_SURFACE[s])
        if first:
            P(rng.choice([f"Doctor sahab, {dur_txt} {surf} hai.", f"Mujhe {dur_txt} {surf} ho raha hai.", f"{surf.capitalize()} hai, {dur_txt}."]))
            first = False
        elif rng.random() < 0.3:
            D(f"{surf.capitalize()} bhi hai kya?")
            P(rng.choice([f"Haan ji, {dur_txt}.", "Haan, thoda sa."]))
            if "thoda" in turns[-1]["text"]:
                dur = None
        else:
            P(rng.choice([f"Aur {surf} bhi hai {dur_txt}.", f"Saath mein {surf} bhi hai, {dur_txt}."]))
        gold["symptoms"].append({"concept_id": s, "present": True, "duration_days": float(dur) if dur else None})

    for s in rng.sample(scenario.negatives, k=min(len(scenario.negatives), rng.choice([1, 2]))):
        surf = rng.choice(SX_SURFACE[s])
        D(rng.choice([f"{surf.capitalize()} hai kya?", f"Koi {surf}?"]))
        if rng.random() < 0.5:
            P(rng.choice([f"Nahi, {surf} nahi hai.", f"Nahi ji, {surf} to nahi hai."]))
        else:
            P(rng.choice(["Nahi ji.", "Nahi, bilkul nahi."]))
        gold["symptoms"].append({"concept_id": s, "present": False, "duration_days": None})
        if rng.random() < 0.3:
            P(rng.choice(["Achha.", "Hmm."]))  # filler

    history = sorted(set(profile["history"]) | set(scenario.history))
    D(rng.choice(["Pehle se koi bimari hai?", "Koi purani bimari?"]))
    if history:
        parts = [rng.choice(COND_SURFACE[h]) for h in history]
        P("Haan, mujhe " + " aur ".join(parts) + " hai, kaafi saal se.")
        gold["history"] = history
    else:
        P(rng.choice(["Nahi, koi bimari nahi hai.", "Nahi ji, kuch nahi."]))

    if mention_allergy:
        D(rng.choice(["Kisi dawai se allergy hai?", "Koi dawai suit nahi karti?"]))
        if profile["allergy"]:
            a = profile["allergy"]
            P(rng.choice([f"Haan, {rng.choice(ALLERGY_SURFACE[a])} se allergy hai, daane nikal aaye the.",
                          f"{rng.choice(ALLERGY_SURFACE[a]).capitalize()} se reaction hua tha ek baar."]))
            gold["allergies"] = [a]
        else:
            P(rng.choice(["Nahi, koi allergy nahi hai.", "Nahi ji, aisa kuch nahi."]))
            gold["allergies"] = ["no_known_allergy"]

    vit_txt = []
    for v in scenario.vitals:
        t, g = _vital(v, rng, scenario.dx)
        vit_txt.append(t)
        gold["vitals"].append(g)
    if vit_txt:
        D(" ".join(vit_txt))

    dx_surf = rng.choice(COND_SURFACE[scenario.dx])
    if scenario.dx == "t2dm":
        D(f"Aapki {dx_surf} abhi uncontrolled hai.")
    elif scenario.dx == "hypertension":
        D(f"Aapka {dx_surf} abhi control mein kam hai, dawai badhani padegi.")
    else:
        D(rng.choice([f"Lagta hai ye {dx_surf} hai.", f"Ye {dx_surf} lag raha hai.", f"Mujhe {dx_surf} lag raha hai."]))

    meds = [Rx(**vars(r)) for r in scenario.meds]
    if conflict_allergy:
        cd = CONFLICT_DRUG[conflict_allergy]
        meds = [m for m in meds if m.drug_id != cd[0]] + [Rx(*cd)]
        gold["expected_flags"].append("allergy_conflict")
    if inappropriate_abx:
        meds.append(Rx("azithromycin", 500, "mg", "OD", 3))
        gold["expected_flags"].append("antibiotic_for_viral")
    if scenario.dx == "dengue":
        D("Brufen ya koi painkiller mat lijiye, sirf paracetamol.")
    for rx in meds:
        D(_rx_sentence(rx, rng))
        gold["medications"].append(vars(rx))
    if profile["allergy"] and any(m.drug_id in CONFLICT_CLASS[profile["allergy"]] for m in meds) \
            and "allergy_conflict" not in gold["expected_flags"]:
        gold["expected_flags"].append("allergy_conflict")

    D(rng.choice(["Paani zyada piyiye aur aaraam kariye.", "Paani khoob piyiye, aaraam kariye."]))
    fu = rng.choice([3, 5, 7]) if not chronic else rng.choice([14, 30])
    fu_txt = {14: "do hafte", 30: "ek mahine"}[fu] if fu in (14, 30) else f"{NUMW[fu]} din"
    D(f"{fu_txt.capitalize()} baad dikhaiye.")
    gold["follow_up_days"] = float(fu)
    P(rng.choice(["Theek hai doctor sahab, dhanyavaad.", "Ji, shukriya."]))

    return {"consult_id": f"{pid}-V{visit_no}", "patient_id": pid, "visit_no": visit_no, "date": vdate.isoformat(),
            "scenario": scenario.name, "turns": turns, "gold": gold}


def generate(n_patients: int = 40, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    out = []
    acute = [s for s in SCENARIOS if s.name not in {"t2dm", "hypertension", "asthma"}]
    for i in range(1, n_patients + 1):
        pid = f"P{i:03d}"
        r = rng.random()
        profile = {
            "history": rng.choice([[], [], ["t2dm"], ["hypertension"], ["hypothyroidism"], ["t2dm", "hypertension"]]),
            "allergy": rng.choice(["penicillin_allergy", "sulfonamide_allergy", "aspirin_allergy"]) if r < 0.35 else None,
        }
        n_visits = rng.choice([1, 2, 2, 3])
        d = date(2026, 8, 1) + timedelta(days=rng.randint(0, 40))
        for v in range(1, n_visits + 1):
            if "t2dm" in profile["history"] and rng.random() < 0.4:
                sc = SC["t2dm"]
            elif "hypertension" in profile["history"] and rng.random() < 0.4:
                sc = SC["hypertension"]
            else:
                sc = rng.choice(acute)
            conflict = None
            mention = True
            if v > 1 and profile["allergy"] and rng.random() < 0.6:
                conflict, mention = profile["allergy"], rng.random() < 0.25  # usually not re-asked at follow-up
            inappropriate = sc.name in {"viral_urti", "viral_fever"} and rng.random() < 0.35
            out.append(make_consult(rng, pid, v, d, sc, profile, inappropriate, conflict, mention))
            d += timedelta(days=rng.randint(10, 45))
    return out


def main(out_dir: str = "data/synthetic") -> None:
    data = generate()
    p = Path(out_dir)
    p.mkdir(parents=True, exist_ok=True)
    with open(p / "consults.jsonl", "w", encoding="utf-8") as fh:
        for c in data:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"wrote {len(data)} consults for {len({c['patient_id'] for c in data})} patients -> {p/'consults.jsonl'}")


if __name__ == "__main__":
    main()
