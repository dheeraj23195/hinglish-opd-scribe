"""Serialise a ClinicalNote as a FHIR R4 document Bundle.

Shape follows the spirit of the NRCeS/ABDM *OPConsultRecord*: a
Composition (status = preliminary, because an AI draft must be signed by
the doctor) whose sections reference Condition, AllergyIntolerance,
Observation and MedicationRequest resources.

Codes: SNOMED CT (http://snomed.info/sct) for clinical concepts, LOINC for
vital signs, UCUM units. Absent symptoms ("khansi nahi hai") are kept as
Conditions with verificationStatus = refuted, so pertinent negatives
survive into the record.
"""
from __future__ import annotations

import uuid
from typing import Any

from .lexicon import concepts, drugs
from .schema import ClinicalNote

SCT = "http://snomed.info/sct"
LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"

FREQ = {"OD": (1, 1), "BD": (2, 1), "TDS": (3, 1), "QID": (4, 1), "HS": (1, 1), "SOS": (None, None)}
VITAL_LOINC = {
    "temperature": ("8310-5", "Body temperature"),
    "pulse": ("8867-4", "Heart rate"),
    "spo2": ("59408-5", "Oxygen saturation in Arterial blood by Pulse oximetry"),
    "fasting_glucose": ("1558-6", "Fasting glucose [Mass/volume] in Serum or Plasma"),
}


def _uid() -> str:
    return str(uuid.uuid4())


def _cc(system: str, code: str, display: str) -> dict:
    if code:
        return {"coding": [{"system": system, "code": code, "display": display}], "text": display}
    return {"text": display}  # uncoded but still human-readable


def to_fhir(note: ClinicalNote, deterministic_ids: bool = False) -> dict[str, Any]:
    cdb, ddb = concepts(), drugs()
    counter = iter(range(1, 10_000))
    uid = (lambda: f"{note.encounter_id}-{next(counter)}") if deterministic_ids else _uid

    pid, eid = f"pat-{note.patient_id}", f"enc-{note.encounter_id}"
    entries: list[dict] = []
    sections: dict[str, list[str]] = {k: [] for k in ("complaints", "history", "allergies", "vitals", "diagnosis", "medications")}

    def add(res: dict, section: str | None = None) -> str:
        rid = res["id"]
        entries.append({"fullUrl": f"urn:uuid:{rid}", "resource": res})
        if section:
            sections[section].append(f"{res['resourceType']}/{rid}")
        return rid

    add({"resourceType": "Patient", "id": pid, "identifier": [{"system": "urn:opdscribe:pseudonym", "value": note.patient_id}]})
    enc: dict = {"resourceType": "Encounter", "id": eid, "status": "finished",
                 "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB", "display": "ambulatory"},
                 "subject": {"reference": f"Patient/{pid}"}}
    if note.date:
        enc["period"] = {"start": note.date}
    add(enc)

    for f in note.findings:
        c = cdb[f.concept_id]
        res: dict = {
            "resourceType": "Condition", "id": uid(),
            "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]},
            "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                                               "code": ("confirmed" if f.is_diagnosis else "unconfirmed") if f.present else "refuted"}]},
            "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-category",
                                      "code": "encounter-diagnosis" if f.is_diagnosis else "problem-list-item"}]}],
            "code": _cc(SCT, c.snomed_code, c.preferred_term),
            "subject": {"reference": f"Patient/{pid}"}, "encounter": {"reference": f"Encounter/{eid}"},
            "note": [{"text": f"Evidence: {f.evidence}"}] if f.evidence else [],
        }
        if f.duration_days:
            res["onsetString"] = f"{f.duration_days:g} day(s) before encounter"
        if not res["note"]:
            res.pop("note")
        section = "diagnosis" if f.is_diagnosis else ("complaints" if f.category == "symptom" else "history")
        add(res, section)

    for a in note.allergies:
        c = cdb[a.concept_id]
        add({"resourceType": "AllergyIntolerance", "id": uid(),
             "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", "code": "active"}]},
             "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification", "code": "unconfirmed"}]},
             "code": _cc(SCT, c.snomed_code, c.preferred_term), "patient": {"reference": f"Patient/{pid}"}}, "allergies")

    for v in note.vitals:
        obs: dict = {"resourceType": "Observation", "id": uid(), "status": "preliminary",
                     "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs"}]}],
                     "subject": {"reference": f"Patient/{pid}"}, "encounter": {"reference": f"Encounter/{eid}"}}
        if v.name == "bp":
            obs["code"] = _cc(LOINC, "85354-9", "Blood pressure panel")
            obs["component"] = [
                {"code": _cc(LOINC, "8480-6", "Systolic blood pressure"), "valueQuantity": {"value": v.value, "unit": "mmHg", "system": UCUM, "code": "mm[Hg]"}},
                {"code": _cc(LOINC, "8462-4", "Diastolic blood pressure"), "valueQuantity": {"value": v.value2, "unit": "mmHg", "system": UCUM, "code": "mm[Hg]"}},
            ]
        else:
            code, disp = VITAL_LOINC[v.name]
            obs["code"] = _cc(LOINC, code, disp)
            obs["valueQuantity"] = {"value": v.value, "unit": v.unit, "system": UCUM, "code": v.unit}
        add(obs, "vitals")

    for m in note.medications:
        d = ddb[m.drug_id]
        dosage: dict = {"text": " ".join(str(x) for x in (d.generic, f"{m.dose_value:g} {m.dose_unit}" if m.dose_value else "", m.frequency or "", f"x {m.duration_days:g} days" if m.duration_days else "") if x)}
        if m.frequency == "SOS":
            dosage["asNeededBoolean"] = True
        elif m.frequency in FREQ:
            fr, per = FREQ[m.frequency]
            rep: dict = {"frequency": fr, "period": per, "periodUnit": "d"}
            if m.duration_days:
                rep["boundsDuration"] = {"value": m.duration_days, "unit": "d", "system": UCUM, "code": "d"}
            if m.frequency == "HS":
                rep["when"] = ["HS"]
            dosage["timing"] = {"repeat": rep}
        if m.dose_value and m.dose_unit in {"mg", "ml", "mcg", "g"}:
            dosage["doseAndRate"] = [{"doseQuantity": {"value": m.dose_value, "unit": m.dose_unit, "system": UCUM, "code": m.dose_unit}}]
        add({"resourceType": "MedicationRequest", "id": uid(), "status": "draft", "intent": "proposal",
             "medicationCodeableConcept": _cc(SCT, d.snomed_code, d.generic),
             "subject": {"reference": f"Patient/{pid}"}, "encounter": {"reference": f"Encounter/{eid}"},
             "dosageInstruction": [dosage]}, "medications")

    titles = {"complaints": "Chief complaints", "history": "Medical history", "allergies": "Allergies",
              "vitals": "Vital signs", "diagnosis": "Diagnosis", "medications": "Medications"}
    comp_sections = [{"title": titles[k], "entry": [{"reference": r} for r in v]} for k, v in sections.items() if v]
    extra = []
    if note.safety_flags:
        extra.append("Safety flags: " + " | ".join(f"[{f.severity}] {f.message}" for f in note.safety_flags))
    if note.prior_context and note.prior_context.get("n_previous_visits"):
        extra.append(f"Prior visits: {note.prior_context['n_previous_visits']}")
    if note.advice:
        comp_sections.append({"title": "Advice", "text": {"status": "generated", "div": "<div xmlns=\"http://www.w3.org/1999/xhtml\">" + " ".join(_esc(a) for a in note.advice) + "</div>"}})
    if extra:
        comp_sections.append({"title": "Scribe notes (AI draft)", "text": {"status": "generated", "div": "<div xmlns=\"http://www.w3.org/1999/xhtml\">" + " ".join(_esc(e) for e in extra) + "</div>"}})

    composition = {
        "resourceType": "Composition", "id": uid(), "status": "preliminary",
        "type": _cc(SCT, "371530004", "Clinical consultation report"),
        "subject": {"reference": f"Patient/{pid}"}, "encounter": {"reference": f"Encounter/{eid}"},
        "date": (note.date + "T00:00:00+05:30") if note.date and "T" not in note.date else (note.date or "2026-01-01T00:00:00+05:30"),
        "author": [{"display": "opdscribe (AI draft, pending clinician review)"}],
        "title": "OPD consultation note", "section": comp_sections,
    }
    entries.insert(0, {"fullUrl": f"urn:uuid:{composition['id']}", "resource": composition})
    return {"resourceType": "Bundle", "id": uid(), "type": "document",
            "timestamp": composition["date"], "identifier": {"system": "urn:opdscribe:bundle", "value": note.encounter_id},
            "entry": entries}


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def validate(bundle: dict) -> None:
    """Structural validation with fhir.resources (R4B models, wire-compatible
    with R4 for the resources used here). Raises on invalid input."""
    from fhir.resources.R4B.bundle import Bundle

    Bundle.model_validate(bundle) if hasattr(Bundle, "model_validate") else Bundle.parse_obj(bundle)
