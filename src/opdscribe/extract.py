"""Rule-based clinical fact extraction from a diarised Hinglish consult.

Design goals
------------
* Deterministic and auditable: every extracted fact keeps the utterance it
  came from (`evidence`), so a doctor can check it in one click.
* Hinglish-aware negation: Hindi negates *after* the noun
  ("khansi nahi hai"), English before ("no cough"); answers like
  "Nahi ji" are linked back to the doctor's question.
* Pluggable: `extract()` is the baseline; an LLM extractor can implement the
  same signature (see `opdscribe.llm_extract`).
"""
from __future__ import annotations

import re
from typing import Optional

from .lexicon import Matcher, drugs
from .normalize import normalize_text, phonetic_key
from .schema import Allergy, ClinicalNote, Finding, Medication, Turn, Vital

NEG_TOKENS = {"nahi", "nahin", "nai", "nhi", "no", "not", "never", "mat", "नहीं", "without", "denies"}
NEG_KEYS = {"nai", "nhi", "ni"}
AFFIRM = {"haan", "ha", "han", "ji", "yes", "hmm", "bilkul", "haanji"}
CLAUSE_BREAK = {"lekin", "par", "but", "magar", "aur", "and", "bas", "sirf", "however"}
QUESTION_WORDS = {"kya", "kab", "kitne", "kitna", "kaisa", "kaise", "koi", "any"}
ALLERGY_WORDS = {"allergy", "allergic", "reaction", "elarji", "एलर्जी"}
DISFLUENCIES = {"haan", "achha", "matlab", "hmm", "umm", "arre", "na", "uh"}  # skipped inside attribute windows

UNIT_DAYS = {
    "din": 1, "dino": 1, "dinon": 1, "day": 1, "days": 1,
    "hafte": 7, "hafta": 7, "hafton": 7, "week": 7, "weeks": 7,
    "mahine": 30, "mahina": 30, "month": 30, "months": 30, "saal": 365, "year": 365, "years": 365,
}

FREQ_PATTERNS = [  # order matters: more specific first
    (r"\b(?:din mein |roz |daily )?(?:4|char|chaar) (?:baar|bar|times)\b|\bqid\b", "QID"),
    (r"\b(?:din mein |roz )?(?:3|teen) (?:baar|bar|times)\b|\btds\b|\btid\b|\bthrice\b|\bsubah dopahar (?:aur )?(?:shaam|raat)\b", "TDS"),
    (r"\b(?:din mein |roz )?(?:2|do) (?:baar|bar|times)\b|\bbd\b|\bbid\b|\btwice\b|\bsubah (?:aur )?(?:shaam|raat)\b", "BD"),
    (r"\b(?:din mein |roz )?(?:1|ek) (?:baar|bar|time)\b|\bod\b|\bonce\b|\broz ek\b", "OD"),
    (r"\bzarurat (?:pade|padne par|ho)\b|\bsos\b|\bjab (?:bukhar|dard) ho\b|\bif needed\b", "SOS"),
    (r"\braat ko\b|\bsone se pehle\b|\bhs\b|\bbedtime\b", "HS"),
]

_matcher_cache: dict[bool, Matcher] = {}


def get_matcher(use_phonetic: bool = True) -> Matcher:
    if use_phonetic not in _matcher_cache:
        _matcher_cache[use_phonetic] = Matcher(use_phonetic=use_phonetic)
    return _matcher_cache[use_phonetic]


# ---------------------------------------------------------------------------
# Speaker roles
# ---------------------------------------------------------------------------
_DOCTOR_CUES = {"lijiye", "kariye", "dikhaiye", "tablet", "mg", "khaiye", "piyiye", "test", "karwaiye",
                "batayiye", "boliye", "lagta", "prescribe", "continue", "dawai"}


def assign_roles(turns: list[Turn]) -> list[Turn]:
    """Map raw diarisation labels to doctor/patient.

    Heuristic: the doctor asks more questions and uses prescriptive verbs and
    drug names. Works for 2-speaker consults; extra speakers (attendants) are
    labelled `patient` (they speak on the patient's behalf in Indian OPDs)."""
    labels = {t.speaker for t in turns}
    if labels <= {"doctor", "patient"}:
        return turns
    m = get_matcher()
    score = {lab: 0.0 for lab in labels}
    for t in turns:
        toks = normalize_text(t.text)
        score[t.speaker] += sum(tok in _DOCTOR_CUES for tok in toks)
        score[t.speaker] += 1.5 * sum(x.kind == "drug" for x in m.find(toks, {"drug"}))
        score[t.speaker] += 0.5 * (("?" in t.text) or any(tok in QUESTION_WORDS for tok in toks))
    doctor = max(score, key=score.get)
    return [Turn("doctor" if t.speaker == doctor else "patient", t.text, t.start, t.end) for t in turns]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _is_neg(tok: str) -> bool:
    return tok in NEG_TOKENS or phonetic_key(tok) in NEG_KEYS


def _is_question(turn: Turn, toks: list[str]) -> bool:
    return "?" in turn.text or (len(toks) > 0 and toks[-1] in {"kya", "na"}) or (toks[:1] and toks[0] in QUESTION_WORDS) or "kya" in toks


def _negated(toks: list[str], start: int, end: int, blocked: set[int]) -> bool:
    # Hindi: negation after the noun, within the clause
    seen = 0
    for j in range(end, len(toks)):
        if toks[j] in DISFLUENCIES:
            continue
        if toks[j] in CLAUSE_BREAK or j in blocked or seen >= 4:
            break
        if _is_neg(toks[j]):
            return True
        seen += 1
    # English / "koi ... nahi": negation before
    for j in range(start - 1, max(-1, start - 3), -1):
        if toks[j] in CLAUSE_BREAK or j in blocked:
            break
        if toks[j] in {"no", "not", "without", "denies"}:
            return True
    return False


def _duration_near(toks: list[str], start: int, end: int) -> Optional[float]:
    toks = [t if t not in DISFLUENCIES else "" for t in toks]
    keep = [i for i, t in enumerate(toks) if t]
    pos = {i: k for k, i in enumerate(keep)}
    toks = [toks[i] for i in keep]
    start = pos.get(start, start if start < len(toks) else len(toks) - 1)
    end = pos.get(end, len(toks)) if end < len(keep) else len(toks)
    best: Optional[tuple[int, float]] = None
    lo, hi = max(0, start - 6), min(len(toks), end + 7)
    for j in range(lo, hi - 1):
        if re.fullmatch(r"\d+(\.\d+)?", toks[j]) and toks[j + 1] in UNIT_DAYS:
            # skip "N din ke liye" (that's a treatment duration, not symptom duration)
            if j + 3 < len(toks) and toks[j + 2] == "ke" and toks[j + 3] == "liye":
                continue
            dist = min(abs(j - start), abs(j - end))
            val = float(toks[j]) * UNIT_DAYS[toks[j + 1]]
            if best is None or dist < best[0]:
                best = (dist, val)
    if best is None:
        for j in range(lo, hi):
            if toks[j] == "kal":
                return 1.0
            if toks[j] == "parson":
                return 2.0
    return best[1] if best else None


def _vitals(toks: list[str], evidence: str) -> tuple[list[Vital], set[int]]:
    s = " ".join(toks)
    out: list[Vital] = []
    used: set[int] = set()

    def span(m: re.Match) -> set[int]:
        a = s[: m.start()].count(" ")
        b = a + s[m.start(): m.end()].count(" ") + 1
        return set(range(a, b))

    for m in re.finditer(r"\b(?:bp|blood pressure)\s+(?:hai\s+)?(\d{2,3})\s*(?:by|/|upon|over|par)\s*(\d{2,3})", s):
        out.append(Vital("bp", float(m.group(1)), float(m.group(2)), "mm[Hg]", evidence)); used |= span(m)
    for m in re.finditer(r"\b(?:temperature|temp|bukhar|taap)\s+(?:hai\s+)?(\d{2,3}(?:\.\d)?)", s):
        v = float(m.group(1))
        if 94 <= v <= 108:
            out.append(Vital("temperature", v, None, "[degF]", evidence)); used |= span(m)
    for m in re.finditer(r"\b(?:pulse|heart rate)\s+(?:hai\s+)?(\d{2,3})", s):
        out.append(Vital("pulse", float(m.group(1)), None, "/min", evidence)); used |= span(m)
    for m in re.finditer(r"\b(?:spo2|oxygen|saturation)\s+(?:hai\s+)?(\d{2,3})", s):
        out.append(Vital("spo2", float(m.group(1)), None, "%", evidence)); used |= span(m)
    for m in re.finditer(r"\b(?:fasting sugar|sugar fasting|fasting)\s+(?:hai\s+)?(\d{2,3})", s):
        out.append(Vital("fasting_glucose", float(m.group(1)), None, "mg/dL", evidence)); used |= span(m)
    return out, used


def _med_attrs(toks: list[str], start: int, stop: int) -> dict:
    win = [t for t in toks[start:stop] if t not in DISFLUENCIES]
    s = " ".join(win)
    out: dict = {}
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(mg|ml|mcg|g)\b", s)
    if m:
        out["dose_value"], out["dose_unit"] = float(m.group(1)), m.group(2)
    elif len(win) > 1 and re.fullmatch(r"\d{2,4}", win[1]):  # "dolo 650"
        out["dose_value"], out["dose_unit"] = float(win[1]), "mg"
    elif re.search(r"\b(\d+)\s*(puff|puffs)\b", s):
        mm = re.search(r"\b(\d+)\s*(puff|puffs)\b", s)
        out["dose_value"], out["dose_unit"] = float(mm.group(1)), "puff"
    for pat, code in FREQ_PATTERNS:
        if re.search(pat, s):
            out["frequency"] = code
            break
    m = re.search(r"\b(\d+(?:\.\d+)?)\s+(din|day|days|hafte|hafta|week|weeks|mahine|month|months)\s+(?:ke liye|liye|tak|for)\b", s)
    if not m:
        m = re.search(r"\bfor\s+(\d+(?:\.\d+)?)\s+(day|days|week|weeks|month|months)\b", s)
    if m:
        out["duration_days"] = float(m.group(1)) * UNIT_DAYS[m.group(2)]
    return out


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------
def extract(turns: list[Turn], patient_id: str = "anon", encounter_id: str = "enc", date: str = "",
            use_phonetic: bool = True) -> ClinicalNote:
    turns = assign_roles(turns)
    m = get_matcher(use_phonetic)
    note = ClinicalNote(patient_id=patient_id, encounter_id=encounter_id, date=date)
    findings: dict[tuple[str, bool], Finding] = {}
    allergies: dict[str, Allergy] = {}
    meds: dict[str, Medication] = {}

    pending_q: list[tuple[str, str]] = []  # (concept_id, category) asked by doctor, awaiting answer
    allergy_q = False

    def put_finding(f: Finding) -> None:
        k = (f.concept_id, f.is_diagnosis)
        if k in findings:
            old = findings[k]
            old.present = f.present  # latest statement wins
            old.duration_days = old.duration_days or f.duration_days
            old.evidence = old.evidence or f.evidence
        else:
            findings[k] = f

    for turn in turns:
        toks = normalize_text(turn.text, canonical=use_phonetic)
        if not toks:
            continue
        vit, masked = _vitals(toks, turn.text)
        note.vitals.extend(vit)
        work = ["_" if i in masked else t for i, t in enumerate(toks)]
        is_doc = turn.speaker == "doctor"
        question = _is_question(turn, toks)
        allergy_ctx = any(t in ALLERGY_WORDS for t in work) or (not is_doc and allergy_q) or "suit nahi" in " ".join(work)

        drug_spans = m.find(work, {"drug"})
        concept_spans = m.find(work, {"symptom", "condition"})
        span_tokens = {i for x in drug_spans + concept_spans for i in range(x.start, x.end)}

        # ---------------- allergies ----------------
        if allergy_ctx:
            allergens = m.find(work, {"allergy"})
            neg_any = any(_is_neg(t) for t in work)
            if allergens:
                for a in allergens:
                    if not _negated(work, a.start, a.end, span_tokens - set(range(a.start, a.end))):
                        allergies[a.ref_id] = Allergy(a.ref_id, turn.text)
            elif not is_doc and neg_any:
                allergies.setdefault("no_known_allergy", Allergy("no_known_allergy", turn.text))
            if not is_doc:
                allergy_q = False
                pending_q = []
                continue
        if is_doc:
            allergy_q = (any(t in ALLERGY_WORDS for t in work) or "suit" in work) and not m.find(work, {"allergy"})

        # ---------------- question -> answer linking ----------------
        if not is_doc and pending_q and not concept_spans:
            first = work[0]
            if _is_neg(first) or any(_is_neg(t) for t in work[:3]):
                for cid, cat in pending_q:
                    put_finding(Finding(cid, cat, False, None, "patient", False, turn.text))
            elif first in AFFIRM:
                dur = _duration_near(work, 0, len(work))
                for cid, cat in pending_q:
                    put_finding(Finding(cid, cat, True, dur, "patient", False, turn.text))
        if not is_doc:
            pending_q = []

        # ---------------- symptoms & conditions ----------------
        for x in concept_spans:
            blocked = span_tokens - set(range(x.start, x.end))
            neg = _negated(work, x.start, x.end, blocked)
            if is_doc and question:
                pending_q.append((x.ref_id, x.category))
                continue
            if is_doc:
                if x.category == "condition" and not neg:
                    put_finding(Finding(x.ref_id, "condition", True, None, "doctor", True, turn.text))
                continue
            dur = _duration_near(work, x.start, x.end) if x.category == "symptom" else None
            put_finding(Finding(x.ref_id, x.category, not neg, dur, "patient", False, turn.text))

        # ---------------- medications (doctor, not questions) ----------------
        if is_doc and not question and drug_spans:
            for i, d in enumerate(drug_spans):
                stop = drug_spans[i + 1].start if i + 1 < len(drug_spans) else len(work)
                if _negated(work, d.start, d.end, set()):
                    continue
                attrs = _med_attrs(work, d.start, stop)
                if d.ref_id in meds:
                    for k, v in attrs.items():
                        setattr(meds[d.ref_id], k, getattr(meds[d.ref_id], k) or v)
                else:
                    meds[d.ref_id] = Medication(d.ref_id, evidence=turn.text, **attrs)

        # ---------------- follow-up & advice ----------------
        if is_doc:
            s = " ".join(t for t in work if t not in DISFLUENCIES)
            fm = re.search(r"\b(\d+(?:\.\d+)?)\s+(din|hafte|hafta|week|weeks|days|mahine)\s+(?:baad|ke baad|later|after)\b", s)
            if fm and any(w in work for w in ("dikhaiye", "dikhana", "aaiye", "aana", "follow", "milte", "milna")):
                note.follow_up_days = float(fm.group(1)) * UNIT_DAYS[fm.group(2)]
            if any(w in work for w in ("paani", "aaraam", "rest", "parhez", "avoid", "fluids", "walk", "exercise")):
                note.advice.append(turn.text)

    note.findings = list(findings.values())
    note.allergies = list(allergies.values())
    if any(a.concept_id != "no_known_allergy" for a in note.allergies):
        note.allergies = [a for a in note.allergies if a.concept_id != "no_known_allergy"]
    note.medications = list(meds.values())
    return note


def antibiotics_in(note: ClinicalNote) -> list[str]:
    db = drugs()
    return [m.drug_id for m in note.medications if db[m.drug_id].is_antibiotic]
