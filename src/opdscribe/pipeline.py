"""End-to-end: audio/transcript -> structured note -> safety -> memory -> FHIR."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import fhir, safety
from .extract import extract
from .memory import PatientMemory, reconcile
from .render import to_markdown
from .schema import ClinicalNote, Turn


@dataclass
class ScribeResult:
    note: ClinicalNote
    fhir_bundle: dict
    markdown: str
    reconciliation: dict


class Scribe:
    def __init__(self, memory: Optional[PatientMemory] = None, use_memory: bool = True, asr=None) -> None:
        self.memory = memory or PatientMemory()
        self.use_memory = use_memory
        self.asr = asr  # any object with .transcribe(path) -> list[Turn]

    def run_audio(self, audio_path: str, patient_id: str, encounter_id: str, date: str) -> ScribeResult:
        if self.asr is None:
            raise RuntimeError("No ASR backend configured; see opdscribe.asr")
        return self.run(self.asr.transcribe(audio_path), patient_id, encounter_id, date)

    def run(self, turns: list[Turn], patient_id: str, encounter_id: str, date: str, save: bool = True) -> ScribeResult:
        note = extract(turns, patient_id, encounter_id, date)
        prior = self.memory.prior_context(patient_id, before_date=date) if self.use_memory else {}
        note.prior_context = prior
        note.safety_flags = safety.check(note, known_allergies=set(prior.get("known_allergies", [])))
        rec = reconcile(note, prior)
        bundle = fhir.to_fhir(note)
        if save:
            self.memory.save(note)
        return ScribeResult(note, bundle, to_markdown(note, rec), rec)
