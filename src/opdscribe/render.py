"""Doctor-facing SOAP note (Markdown) rendered from a ClinicalNote."""
from __future__ import annotations

from .lexicon import concepts, drugs
from .schema import ClinicalNote


def _term(cid: str) -> str:
    return concepts()[cid].preferred_term


def to_markdown(note: ClinicalNote, reconciliation: dict | None = None) -> str:
    ddb = drugs()
    L = [f"# OPD note — patient {note.patient_id} — {note.date}", "", "_AI draft. Verify before signing._", ""]
    pc = note.prior_context or {}
    if pc.get("n_previous_visits"):
        L += ["## Since last visit", f"- Previous visits: {pc['n_previous_visits']} (last: {pc.get('last_visit_date', '?')})"]
        if pc.get("chronic_conditions"):
            L.append("- Known conditions: " + ", ".join(_term(c) for c in pc["chronic_conditions"]))
        if pc.get("known_allergies"):
            L.append("- **Known allergies: " + ", ".join(_term(c) for c in pc["known_allergies"]) + "**")
        if reconciliation:
            for k, v in reconciliation.items():
                if v:
                    L.append(f"- {k.replace('_', ' ').capitalize()}: {', '.join(v)}")
        L.append("")
    if note.safety_flags:
        L.append("## Safety flags")
        L += [f"- **{f.severity.upper()}** — {f.message}" for f in note.safety_flags]
        L.append("")
    L.append("## S — Subjective")
    for f in note.symptoms(present=True):
        d = f" × {f.duration_days:g} d" if f.duration_days else ""
        L.append(f"- {_term(f.concept_id)}{d}")
    neg = note.symptoms(present=False)
    if neg:
        L.append("- Denies: " + ", ".join(_term(f.concept_id) for f in neg))
    if note.history():
        L.append("- History: " + ", ".join(_term(f.concept_id) for f in note.history() if f.present))
    if note.allergies:
        L.append("- Allergies: " + ", ".join(_term(a.concept_id) for a in note.allergies))
    L += ["", "## O — Objective"]
    for v in note.vitals:
        L.append(f"- {v.name}: {v.value:g}" + (f"/{v.value2:g}" if v.value2 else "") + f" {v.unit}")
    L += ["", "## A — Assessment"]
    L += [f"- {_term(f.concept_id)}" for f in note.diagnoses()] or ["- (not stated)"]
    L += ["", "## P — Plan"]
    for m in note.medications:
        d = ddb[m.drug_id]
        parts = [d.generic, f"{m.dose_value:g} {m.dose_unit}" if m.dose_value else "", m.frequency or "", f"× {m.duration_days:g} d" if m.duration_days else ""]
        L.append("- " + " ".join(p for p in parts if p) + (" _(antibiotic, AWaRe: " + d.aware_group + ")_" if d.is_antibiotic else ""))
    if note.follow_up_days:
        L.append(f"- Follow-up in {note.follow_up_days:g} days")
    for a in note.advice:
        L.append(f"- Advice: “{a}”")
    return "\n".join(L) + "\n"
