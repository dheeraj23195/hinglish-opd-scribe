"""Clinical-severity evaluation.

Two complementary measures:

1. **CS-WER** (clinical-severity-weighted error rate), token level.
   Every reference token gets a clinical category; an error on it costs that
   category's weight. Spelling variants that normalise to the same phonetic
   key (bukhar/bukhaar) cost nothing. Negation deletions, drug and number
   errors dominate; filler-word errors barely count.

       CS-WER = sum(cost of each edit) / sum(weight of reference tokens)

2. **Clinical Error Score** (concept level). Run the same extractor on the
   reference and the ASR transcript and diff the structured notes: missed /
   wrong drug, dose change, negation flip, missed allergy... each error gets
   a severity tier (critical / major / minor). This is the closest proxy to
   "would this change what happens to the patient" that we can compute
   without a clinician in the loop.

Weights below are the team's initial proposal. They will be calibrated
against clinician harm ratings (see docs/metric.md).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..extract import NEG_TOKENS, _is_neg, get_matcher
from ..lexicon import drugs
from ..normalize import phonetic_key
from ..schema import ClinicalNote
from .wer import align

DEFAULT_WEIGHTS = {
    "DRUG": 5.0, "NEGATION": 5.0, "NUMBER": 5.0, "ALLERGY": 5.0,  # critical
    "CLINICAL": 3.0, "REGIMEN": 3.0,  # major
    "OTHER": 1.0,  # minor
    "FILLER": 0.2,  # negligible
}
TIER = {"DRUG": "critical", "NEGATION": "critical", "NUMBER": "critical", "ALLERGY": "critical",
        "CLINICAL": "major", "REGIMEN": "major", "OTHER": "minor", "FILLER": "negligible"}

FILLERS = {"haan", "han", "ji", "achha", "acha", "accha", "toh", "to", "hmm", "ok", "okay", "theek", "thik", "matlab",
           "bas", "na", "arre", "dekhiye", "sir", "doctor", "sahab", "madam", "ha", "umm", "uh", "jee", "aap", "main", "mujhe",
           "hai", "hain", "ho", "tha", "thi", "se", "ka", "ki", "ke", "mein", "me", "bhi", "aur", "kya", "yeh", "ye", "woh", "wo"}
REGIMEN = {"baar", "bar", "din", "dino", "dinon", "hafte", "hafta", "week", "weeks", "days", "day", "mahine", "subah",
           "shaam", "dopahar", "raat", "mg", "ml", "mcg", "liye", "tak", "khane", "baad", "pehle", "khali", "pet", "roz",
           "daily", "twice", "once", "sos", "zarurat", "puff", "puffs", "tablet", "goli", "capsule", "syrup", "inhaler"}
ALLERGY_TOK = {"allergy", "allergic", "reaction", "suit"}
SEV_W = {"critical": 5.0, "major": 3.0, "minor": 1.0}


def _cat_single(tok: str) -> str:
    if _is_neg(tok) or tok in NEG_TOKENS:
        return "NEGATION"
    if re.fullmatch(r"\d+(\.\d+)?", tok):
        return "NUMBER"
    if tok in ALLERGY_TOK:
        return "ALLERGY"
    if tok in REGIMEN:
        return "REGIMEN"
    if tok in FILLERS:
        return "FILLER"
    return "OTHER"


def tag_tokens(tokens: list[str]) -> list[str]:
    """Clinical category for every token (lexicon spans override single-token rules)."""
    cats = [_cat_single(t) for t in tokens]
    for mt in get_matcher().find(tokens):
        cat = "DRUG" if mt.kind == "drug" else ("ALLERGY" if mt.category == "allergy" else "CLINICAL")
        for i in range(mt.start, mt.end):
            if cats[i] not in ("NEGATION", "NUMBER"):
                cats[i] = cat
    return cats


def _hyp_cat(tok: str) -> str:
    c = _cat_single(tok)
    if c == "OTHER" and get_matcher().find([tok], {"drug"}):
        return "DRUG"
    return c


def cs_wer(ref: list[str], hyp: list[str], weights: dict | None = None, forgive_variants: bool = True) -> dict:
    """Returns {'cs_wer', 'by_tier': {tier: cost}, 'n_variant_forgiven'}."""
    w = weights or DEFAULT_WEIGHTS
    cats = tag_tokens(ref)
    total = sum(w[c] for c in cats) or 1.0
    cost = 0.0
    by_tier: dict[str, float] = {"critical": 0.0, "major": 0.0, "minor": 0.0, "negligible": 0.0}
    forgiven = 0
    for op, r, h, i in align(ref, hyp, key=phonetic_key if forgive_variants else None):
        if op == "eq":
            if r != h:
                forgiven += 1  # spelling variant with the same phonetic key: no clinical change
            continue
        if op == "sub":
            c = cats[i] if w[cats[i]] >= w[_hyp_cat(h)] else _hyp_cat(h)
        elif op == "del":
            c = cats[i]
        else:
            c = _hyp_cat(h)
        cost += w[c]
        by_tier[TIER[c]] += w[c]
    return {"cs_wer": cost / total, "by_tier": {k: v / total for k, v in by_tier.items()}, "n_variant_forgiven": forgiven}


# ---------------------------------------------------------------------------
# Concept-level comparison
# ---------------------------------------------------------------------------
@dataclass
class ClinicalError:
    kind: str
    severity: str
    detail: str


def compare_notes(ref: ClinicalNote, hyp: ClinicalNote) -> list[ClinicalError]:
    E: list[ClinicalError] = []

    def fmap(n: ClinicalNote, diag: bool):
        return {f.concept_id: f for f in n.findings if f.is_diagnosis == diag}

    for diag in (False, True):
        r, h = fmap(ref, diag), fmap(hyp, diag)
        label = "diagnosis" if diag else "finding"
        for cid, f in r.items():
            if cid not in h:
                if f.present:
                    E.append(ClinicalError(f"missed_{label}", "major", cid))
                else:
                    E.append(ClinicalError("missed_pertinent_negative", "minor", cid))
            elif h[cid].present != f.present:
                E.append(ClinicalError("negation_flip", "critical", f"{cid}: {f.present}->{h[cid].present}"))
            elif f.duration_days != h[cid].duration_days:
                E.append(ClinicalError("duration_changed", "minor", f"{cid}: {f.duration_days}->{h[cid].duration_days}"))
        for cid, f in h.items():
            if cid not in r and f.present:
                E.append(ClinicalError(f"hallucinated_{label}", "major", cid))

    ra, ha = {a.concept_id for a in ref.allergies}, {a.concept_id for a in hyp.allergies}
    for a in ra - ha:
        E.append(ClinicalError("missed_allergy", "critical" if a != "no_known_allergy" else "minor", a))
    for a in ha - ra:
        E.append(ClinicalError("hallucinated_allergy", "major", a))

    rm, hm = {m.drug_id: m for m in ref.medications}, {m.drug_id: m for m in hyp.medications}
    for d, m in rm.items():
        if d not in hm:
            E.append(ClinicalError("missed_medication", "critical", d))
            continue
        x = hm[d]
        if m.dose_value != x.dose_value:
            E.append(ClinicalError("dose_changed", "critical", f"{d}: {m.dose_value}->{x.dose_value}"))
        if m.frequency != x.frequency:
            E.append(ClinicalError("frequency_changed", "major", f"{d}: {m.frequency}->{x.frequency}"))
        if m.duration_days != x.duration_days:
            E.append(ClinicalError("course_duration_changed", "major", f"{d}: {m.duration_days}->{x.duration_days}"))
    for d in set(hm) - set(rm):
        E.append(ClinicalError("wrong_or_extra_medication", "critical", d + (" (antibiotic)" if drugs()[d].is_antibiotic else "")))

    rv = {(v.name): v for v in ref.vitals}
    hv = {(v.name): v for v in hyp.vitals}
    for k, v in rv.items():
        if k not in hv:
            E.append(ClinicalError("missed_vital", "minor", k))
        elif (v.value, v.value2) != (hv[k].value, hv[k].value2):
            E.append(ClinicalError("vital_changed", "major", f"{k}: {v.value}/{v.value2}->{hv[k].value}/{hv[k].value2}"))
    return E


def clinical_error_score(errors: list[ClinicalError]) -> dict:
    return {
        "score": sum(SEV_W[e.severity] for e in errors),
        "critical": sum(e.severity == "critical" for e in errors),
        "major": sum(e.severity == "major" for e in errors),
        "minor": sum(e.severity == "minor" for e in errors),
    }
