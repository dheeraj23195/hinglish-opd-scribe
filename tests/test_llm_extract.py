"""LLM extractor plumbing, tested with a recorded (fake) model response."""
import json

from opdscribe.llm_extract import build_prompt, hybrid, llm_extract
from opdscribe.schema import Turn

TURNS = [Turn("patient", "Na khoon, na bukhar. Bas loose motion hai."),
         Turn("doctor", "Brufen mat lena. Ondem 4 mg zarurat pade toh.")]

FAKE = json.dumps({
    "findings": [{"concept_id": "fever", "present": False, "duration_days": None, "is_diagnosis": False, "evidence": "Na khoon, na bukhar"},
                 {"concept_id": "diarrhoea", "present": True, "duration_days": None, "is_diagnosis": False, "evidence": "Bas loose motion hai"}],
    "allergies": [],
    "medications": [{"drug_id": "ondansetron", "dose_value": 4, "dose_unit": "mg", "frequency": "SOS", "duration_days": None,
                     "evidence": "Ondem 4 mg zarurat pade toh"},
                    {"drug_id": "metformin", "dose_value": 500, "dose_unit": "mg", "frequency": "BD", "duration_days": None,
                     "evidence": "Metformin 500 subah shaam"},  # hallucinated: must be dropped
                    {"drug_id": "unobtainium", "evidence": "Ondem 4 mg"}],
    "vitals": []})


def test_prompt_lists_closed_vocabularies():
    p = build_prompt(TURNS)
    assert "paracetamol" in p and "fever" in p and "Na khoon, na bukhar" in p


def test_llm_output_validated_against_transcript():
    note, dropped = llm_extract(TURNS, lambda _: "Sure! " + FAKE)
    assert {(f.concept_id, f.present) for f in note.findings} == {("fever", False), ("diarrhoea", True)}
    assert [m.drug_id for m in note.medications] == ["ondansetron"]
    assert len(dropped) == 2


def test_hybrid_keeps_rule_medications():
    empty = json.dumps({"findings": [], "allergies": [], "medications": [], "vitals": []})
    note, _ = hybrid(TURNS, lambda _: empty)
    assert [m.drug_id for m in note.medications] == ["ondansetron"]  # from rules; Brufen stays excluded
