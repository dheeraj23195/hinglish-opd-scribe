"""Longitudinal patient memory (SQLite).

Stores every finalised note per (pseudonymous) patient and builds a
`prior_context` for the next visit:

* chronic conditions and known allergies carried forward
* medications from the last visit -> continued / stopped / new
* symptoms from last visit that are still present today

The store holds no names or phone numbers: `patient_id` is expected to be a
pseudonymous ID (e.g. a hash of the ABHA number) issued upstream.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from .schema import ClinicalNote

CHRONIC = {"t2dm", "hypertension", "asthma", "hypothyroidism"}


class PatientMemory:
    def __init__(self, path: str | Path = ":memory:") -> None:
        # check_same_thread=False + a lock: Streamlit reruns the app on different
        # threads, and one cached Scribe (and its memory) is shared across them.
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.RLock()
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS encounters (encounter_id TEXT PRIMARY KEY, patient_id TEXT, date TEXT, note_json TEXT)"
        )
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_pat ON encounters(patient_id, date)")

    def save(self, note: ClinicalNote) -> None:
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO encounters VALUES (?,?,?,?)",
                (note.encounter_id, note.patient_id, note.date, json.dumps(note.to_dict())),
            )
            self.db.commit()

    def visits(self) -> list[tuple[str, str]]:
        """All remembered (patient_id, date) pairs, oldest first per patient."""
        with self._lock:
            return list(self.db.execute("SELECT patient_id, date FROM encounters ORDER BY patient_id, date"))

    def history(self, patient_id: str, before_date: Optional[str] = None, k: int = 5) -> list[dict]:
        q = "SELECT note_json FROM encounters WHERE patient_id=?"
        args: list = [patient_id]
        if before_date:
            q += " AND date < ?"
            args.append(before_date)
        q += " ORDER BY date DESC LIMIT ?"
        args.append(k)
        with self._lock:
            rows = list(self.db.execute(q, args))
        return [json.loads(r[0]) for r in rows]

    def prior_context(self, patient_id: str, before_date: Optional[str] = None) -> dict:
        past = self.history(patient_id, before_date)
        if not past:
            return {"n_previous_visits": 0}
        conditions, allergies = set(), set()
        for n in past:
            for f in n["findings"]:
                if f["category"] == "condition" and f["present"] and (f["concept_id"] in CHRONIC or not f["is_diagnosis"]):
                    conditions.add(f["concept_id"])
            allergies |= {a["concept_id"] for a in n["allergies"] if a["concept_id"] != "no_known_allergy"}
        last = past[0]
        return {
            "n_previous_visits": len(past),
            "last_visit_date": last["date"],
            "chronic_conditions": sorted(conditions),
            "known_allergies": sorted(allergies),
            "last_medications": [m["drug_id"] for m in last["medications"]],
            "last_diagnoses": [f["concept_id"] for f in last["findings"] if f["is_diagnosis"]],
            "last_symptoms": [f["concept_id"] for f in last["findings"] if f["category"] == "symptom" and f["present"]],
        }


def reconcile(note: ClinicalNote, prior: dict) -> dict:
    """Compare today's note with the previous visit."""
    if not prior or not prior.get("n_previous_visits"):
        return {}
    today = {m.drug_id for m in note.medications}
    last = set(prior.get("last_medications", []))
    today_sx = {f.concept_id for f in note.symptoms(present=True)}
    return {
        "medications_continued": sorted(today & last),
        "medications_new": sorted(today - last),
        "medications_stopped_or_not_mentioned": sorted(last - today),
        "symptoms_persisting": sorted(today_sx & set(prior.get("last_symptoms", []))),
        "allergies_from_history_not_mentioned_today": sorted(
            set(prior.get("known_allergies", [])) - {a.concept_id for a in note.allergies}),
    }
