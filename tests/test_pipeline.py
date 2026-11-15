import json
from pathlib import Path

import pytest

from opdscribe import fhir
from opdscribe.extract import assign_roles, extract
from opdscribe.memory import PatientMemory
from opdscribe.metrics import compare_notes, cs_wer, wer
from opdscribe.normalize import canonicalize, phonetic_key, romanize, tokenize, words_to_digits
from opdscribe.pipeline import Scribe
from opdscribe.schema import Turn
from opdscribe.sim.generate import generate
from opdscribe.sim.gold import gold_note, turns_of

ROOT = Path(__file__).resolve().parents[1]


def T(*pairs):
    return [Turn(s, t) for s, t in pairs]


# ---------------- normalisation ----------------
@pytest.mark.parametrize("a,b", [("bukhar", "bukhaar"), ("khansi", "khaansi"), ("nahi", "nahin"), ("zarurat", "zaroorat")])
def test_spelling_variants_share_key(a, b):
    assert phonetic_key(a) == phonetic_key(b)


def test_distinct_words_keep_distinct_keys():
    assert phonetic_key("din") != phonetic_key("dard")
    assert phonetic_key("metformin") != phonetic_key("metronidazole")


def test_romanize_devanagari():
    assert romanize("बुखार") == "bukhaar"
    assert phonetic_key(romanize("बुखार")) == phonetic_key("bukhar")


def test_number_words_only_before_units():
    assert words_to_digits(["teen", "din", "se"]) == ["3", "din", "se"]
    assert words_to_digits(["de", "do"]) == ["de", "do"]  # "do" = give


def test_canonicalize_function_words():
    assert canonicalize(["deen", "kyaa", "zaroorat"]) == ["din", "kya", "zarurat"]


# ---------------- extraction ----------------
def test_hindi_negation_after_noun():
    n = extract(T(("patient", "Teen din se bukhar hai."), ("patient", "Khansi nahi hai.")))
    f = {x.concept_id: x for x in n.findings}
    assert f["fever"].present and f["fever"].duration_days == 3
    assert not f["cough"].present


def test_bare_answer_links_to_question():
    n = extract(T(("doctor", "Ulti hai kya?"), ("patient", "Nahi ji.")))
    assert [(f.concept_id, f.present) for f in n.findings] == [("vomiting", False)]


def test_negated_prescription_is_not_a_medication():
    n = extract(T(("doctor", "Brufen ya koi painkiller mat lijiye, sirf paracetamol."), ("doctor", "Dolo 650 din mein teen baar lijiye, teen din ke liye.")))
    assert [m.drug_id for m in n.medications] == ["paracetamol"]
    m = n.medications[0]
    assert (m.dose_value, m.frequency, m.duration_days) == (650, "TDS", 3)


def test_allergy_drug_name_overlap():
    n = extract(T(("doctor", "Koi dawai suit nahi karti?"), ("patient", "Septran se reaction hua tha."),
                  ("doctor", "Septran din mein do baar lijiye, paanch din ke liye.")))
    assert [a.concept_id for a in n.allergies] == ["sulfonamide_allergy"]
    assert [m.drug_id for m in n.medications] == ["cotrimoxazole"]


def test_vitals_and_sugar_not_confused_with_diabetes():
    n = extract(T(("doctor", "BP 150 by 96 hai. Fasting sugar 168 aaya hai.")))
    assert {v.name for v in n.vitals} == {"bp", "fasting_glucose"}
    assert not n.findings


def test_role_assignment_from_raw_labels():
    turns = assign_roles(T(("spk_0", "Doctor sahab teen din se bukhar hai."), ("spk_1", "Dolo 650 lijiye din mein teen baar.")))
    assert [t.speaker for t in turns] == ["patient", "doctor"]


def test_synthetic_gold_roundtrip():
    for c in generate(n_patients=8, seed=3):
        assert compare_notes(gold_note(c), extract(turns_of(c))) == []


# ---------------- metrics ----------------
def test_wer_basic():
    assert wer("a b c d".split(), "a x c".split()) == 0.5


def test_cswer_forgives_spelling_but_not_negation():
    ref = tokenize("khansi nahi hai")
    assert cs_wer(ref, tokenize("khaansi nahin hai"))["cs_wer"] == 0
    assert wer(ref, tokenize("khaansi nahin hai")) > 0
    dropped = cs_wer(ref, tokenize("khansi hai"))
    assert dropped["by_tier"]["critical"] > 0


def test_cswer_drug_error_costs_more_than_filler():
    ref = tokenize("achha dolo 650 lijiye")
    assert cs_wer(ref, tokenize("dolo 650 lijiye"))["cs_wer"] < cs_wer(ref, tokenize("achha dolo 65 lijiye"))["cs_wer"]


# ---------------- safety, memory, FHIR ----------------
def _visit(scribe, pid, date, turns):
    return scribe.run(T(*turns), pid, f"{pid}-{date}", date)


def test_memory_catches_allergy_from_previous_visit():
    s = Scribe(PatientMemory())
    _visit(s, "X1", "2026-08-01", [("doctor", "Kisi dawai se allergy hai?"), ("patient", "Haan, penicillin se allergy hai.")])
    r = _visit(s, "X1", "2026-09-01", [("patient", "Gale mein dard hai do din se."), ("doctor", "Gale ka infection lag raha hai."),
                                          ("doctor", "Amoxicillin 500 mg din mein teen baar, paanch din ke liye.")])
    assert any(f.kind == "allergy_conflict" for f in r.note.safety_flags)
    no_mem = Scribe(PatientMemory(), use_memory=False)
    _visit(no_mem, "X1", "2026-08-01", [("doctor", "Kisi dawai se allergy hai?"), ("patient", "Haan, penicillin se allergy hai.")])
    r2 = _visit(no_mem, "X1", "2026-09-01", [("doctor", "Amoxicillin 500 mg din mein teen baar, paanch din ke liye.")])
    assert not any(f.kind == "allergy_conflict" for f in r2.note.safety_flags)


def test_antibiotic_for_viral_flag():
    r = _visit(Scribe(), "X2", "2026-08-01", [("doctor", "Ye viral fever hai."), ("doctor", "Azithral 500 mg roz ek baar teen din ke liye.")])
    kinds = {f.kind for f in r.note.safety_flags}
    assert "antibiotic_for_viral" in kinds and "watch_antibiotic" in kinds


def test_fhir_bundle_validates_and_keeps_negatives():
    c = generate(n_patients=3, seed=5)[0]
    r = Scribe().run(turns_of(c), c["patient_id"], c["consult_id"], c["date"])
    fhir.validate(r.fhir_bundle)
    ver = [e["resource"]["verificationStatus"]["coding"][0]["code"] for e in r.fhir_bundle["entry"] if e["resource"]["resourceType"] == "Condition"]
    assert "refuted" in ver  # pertinent negatives survive
    comp = r.fhir_bundle["entry"][0]["resource"]
    assert comp["resourceType"] == "Composition" and comp["status"] == "preliminary"


def test_example_transcript_runs_through_cli(tmp_path):
    from opdscribe.cli import main
    main(["run", str(ROOT / "data/examples/consult_hinglish.json"), "--patient", "DEMO", "--date", "2026-09-01",
          "--memory", str(tmp_path / "m.sqlite"), "--out", str(tmp_path)])
    out = json.loads((tmp_path / "DEMO-2026-09-01.fhir.json").read_text())
    fhir.validate(out)
