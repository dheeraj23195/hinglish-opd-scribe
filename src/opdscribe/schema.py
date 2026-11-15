"""Core data structures shared across the pipeline.

Everything is a plain dataclass so it serialises to JSON with `asdict`
and can be compared field-by-field in evaluation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class Turn:
    """One diarised utterance. `speaker` is a raw diarisation label
    (e.g. "spk_0") or an already-resolved role ("doctor" / "patient")."""

    speaker: str
    text: str
    start: Optional[float] = None
    end: Optional[float] = None


@dataclass
class Finding:
    """A symptom or condition reported in the consult."""

    concept_id: str
    category: str  # "symptom" | "condition"
    present: bool = True
    duration_days: Optional[float] = None
    source: str = "patient"  # who asserted it: patient (history/complaint) or doctor (diagnosis)
    is_diagnosis: bool = False
    evidence: str = ""  # the utterance the fact was taken from (evidence-linking)


@dataclass
class Medication:
    drug_id: str
    dose_value: Optional[float] = None
    dose_unit: Optional[str] = None
    frequency: Optional[str] = None  # OD | BD | TDS | QID | HS | SOS
    duration_days: Optional[float] = None
    evidence: str = ""


@dataclass
class Allergy:
    concept_id: str  # e.g. penicillin_allergy, or no_known_allergy
    evidence: str = ""


@dataclass
class Vital:
    name: str  # bp | temperature | pulse | spo2 | fasting_glucose
    value: float
    value2: Optional[float] = None  # diastolic for BP
    unit: str = ""
    evidence: str = ""


@dataclass
class SafetyFlag:
    kind: str  # allergy_conflict | antibiotic_for_viral | nsaid_in_dengue | ...
    severity: str  # critical | major | minor
    message: str


@dataclass
class ClinicalNote:
    """Structured output of one consult, before FHIR serialisation."""

    patient_id: str
    encounter_id: str
    date: str
    findings: list[Finding] = field(default_factory=list)
    medications: list[Medication] = field(default_factory=list)
    allergies: list[Allergy] = field(default_factory=list)
    vitals: list[Vital] = field(default_factory=list)
    advice: list[str] = field(default_factory=list)
    follow_up_days: Optional[float] = None
    safety_flags: list[SafetyFlag] = field(default_factory=list)
    prior_context: Optional[dict] = None

    def to_dict(self) -> dict:
        return asdict(self)

    # Convenience views -------------------------------------------------
    def symptoms(self, present: Optional[bool] = None) -> list[Finding]:
        return [f for f in self.findings if f.category == "symptom" and (present is None or f.present == present)]

    def diagnoses(self) -> list[Finding]:
        return [f for f in self.findings if f.is_diagnosis]

    def history(self) -> list[Finding]:
        return [f for f in self.findings if f.category == "condition" and not f.is_diagnosis]
