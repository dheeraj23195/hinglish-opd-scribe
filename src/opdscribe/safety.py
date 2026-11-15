"""Deterministic safety checks run on every note before it is shown.

These are guardrails, not clinical decision support: each flag tells the
doctor *why* it fired and points at the evidence. Rules are intentionally
few and conservative.
"""
from __future__ import annotations

from .lexicon import drugs
from .schema import ClinicalNote, SafetyFlag

VIRAL_DX = {"viral_urti", "viral_fever"}
BACTERIAL_DX = {"uti", "typhoid", "pharyngitis"}

# allergy concept -> drug classes that conflict (critical) or need caution (major)
ALLERGY_CONFLICTS = {
    "penicillin_allergy": ({"penicillin"}, {"cephalosporin"}),
    "sulfonamide_allergy": ({"sulfonamide"}, set()),
    "aspirin_allergy": ({"nsaid"}, set()),
}


def check(note: ClinicalNote, known_allergies: set[str] | None = None) -> list[SafetyFlag]:
    """`known_allergies` comes from longitudinal memory (past visits)."""
    db = drugs()
    flags: list[SafetyFlag] = []
    allergies = {a.concept_id for a in note.allergies} | set(known_allergies or set())
    dx = {f.concept_id for f in note.diagnoses()}

    for med in note.medications:
        d = db[med.drug_id]
        for allergy in allergies:
            hard, soft = ALLERGY_CONFLICTS.get(allergy, (set(), set()))
            source = "mentioned today" if allergy in {a.concept_id for a in note.allergies} else "recorded at a previous visit"
            if d.drug_class in hard:
                flags.append(SafetyFlag("allergy_conflict", "critical",
                                        f"{d.generic} prescribed but patient has {allergy.replace('_', ' ')} ({source})."))
            elif d.drug_class in soft:
                flags.append(SafetyFlag("allergy_caution", "major",
                                        f"{d.generic}: possible cross-reactivity with {allergy.replace('_', ' ')} ({source})."))

    abx = [m for m in note.medications if db[m.drug_id].is_antibiotic]
    if abx and dx & VIRAL_DX and not dx & BACTERIAL_DX:
        names = ", ".join(f"{db[m.drug_id].generic} ({db[m.drug_id].aware_group})" for m in abx)
        flags.append(SafetyFlag("antibiotic_for_viral", "critical",
                                f"Antibiotic prescribed for a diagnosis recorded as viral: {names}. Antibiotics do not treat viral infections."))
    for m in abx:
        if db[m.drug_id].aware_group == "Watch":
            flags.append(SafetyFlag("watch_antibiotic", "minor",
                                    f"{db[m.drug_id].generic} is a WHO AWaRe 'Watch' antibiotic; confirm indication."))
        if m.duration_days is None:
            flags.append(SafetyFlag("antibiotic_no_duration", "major",
                                    f"{db[m.drug_id].generic}: no course duration captured."))

    if "dengue" in dx and any(db[m.drug_id].drug_class == "nsaid" for m in note.medications):
        flags.append(SafetyFlag("nsaid_in_dengue", "critical", "NSAID prescribed with suspected dengue (bleeding risk)."))
    return flags
