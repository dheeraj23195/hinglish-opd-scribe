"""Convert a generator gold record into a ClinicalNote for comparison."""
from __future__ import annotations

from ..schema import Allergy, ClinicalNote, Finding, Medication, Turn, Vital


def gold_note(c: dict) -> ClinicalNote:
    g = c["gold"]
    n = ClinicalNote(c["patient_id"], c["consult_id"], c["date"])
    n.findings = [Finding(s["concept_id"], "symptom", s["present"], s["duration_days"]) for s in g["symptoms"]]
    n.findings += [Finding(h, "condition", True) for h in g["history"]]
    n.findings += [Finding(d, "condition", True, None, "doctor", True) for d in g["diagnoses"]]
    n.allergies = [Allergy(a) for a in g["allergies"]]
    n.medications = [Medication(m["drug_id"], m["dose_value"], m["dose_unit"], m["frequency"], m["duration_days"]) for m in g["medications"]]
    n.vitals = [Vital(v["name"], v["value"], v["value2"]) for v in g["vitals"]]
    n.follow_up_days = g["follow_up_days"]
    return n


def turns_of(c: dict) -> list[Turn]:
    return [Turn(t["speaker"], t["text"]) for t in c["turns"]]
