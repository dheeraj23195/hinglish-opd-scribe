"""Tests for cross-script normalisation, dosing notation and metric calibration."""
from opdscribe.crossscript import preprocess, skeleton
from opdscribe.extract import extract
from opdscribe.metrics import cs_wer
from opdscribe.metrics.calibrate import agreement, fit_weights
from opdscribe.normalize import romanize, tokenize
from opdscribe.schema import Turn


def T(*pairs):
    return [Turn(s, t) for s, t in pairs]


def test_hindi_number_words():
    assert preprocess("डोलो साढ़े छह सौ") == "dolo 650"
    assert preprocess("बीपी एक सौ पचास बाई छियानवे") == "bp 150 by 96"
    assert preprocess("दवाई दो") == "दवाई दो"  # "do" = give, not 2


def test_devanagari_drug_names_match_by_skeleton():
    for dev, lat in [("पैरासिटामोल", "paracetamol"), ("मेटफॉर्मिन", "metformin"), ("अमोक्सिसिलिन", "amoxicillin")]:
        assert skeleton(romanize(dev)) == skeleton(lat)


def test_fully_devanagari_consult():
    n = extract(T(("patient", "तीन दिन से बुखार है।"), ("doctor", "पैरासिटामोल साढ़े छह सौ दिन में तीन बार, तीन दिन के लिए।")))
    assert [(f.concept_id, f.duration_days) for f in n.findings] == [("fever", 3.0)]
    m = n.medications[0]
    assert (m.drug_id, m.dose_value, m.frequency, m.duration_days) == ("paracetamol", 650, "TDS", 3)


def test_indian_dosing_notation():
    n = extract(T(("doctor", "Glycomet 500 mg 1-0-1 khane ke baad, ek mahine.")))
    m = n.medications[0]
    assert (m.frequency, m.duration_days) == ("BD", 30)


def test_dose_per_day_is_not_course_length():
    n = extract(T(("doctor", "Sirf paracetamol 650 din mein teen baar lijiye.")))
    assert n.medications[0].duration_days is None


def test_intensifier_inside_phrase_and_qa_with_other_concepts():
    n = extract(T(("patient", "Gala bahut kharab hai."), ("doctor", "Saans phool rahi hai?"),
                  ("patient", "Haan, do hafte se. Mujhe dama hai.")))
    f = {x.concept_id: x for x in n.findings}
    assert f["sore_throat"].present and f["breathlessness"].duration_days == 14 and "asthma" in f


def test_calibration_agreement_and_fit():
    items = [{"item_id": f"R{i}", "category": c} for i, c in enumerate(["DRUG", "DRUG", "FILLER", "FILLER", "NEGATION", "OTHER"])]
    a = {"R0": 4, "R1": 4, "R2": 0, "R3": 0, "R4": 4, "R5": 1}
    b = {"R0": 4, "R1": 3, "R2": 0, "R3": 1, "R4": 4, "R5": 1}
    ag = agreement({"a": a, "b": b})
    assert ag["alpha"] > 0.8 and ag["weighted_kappa"] > 0.8
    w = fit_weights(items, {"a": a, "b": b})
    assert w["NEGATION"] == 5.0 and w["FILLER"] < w["OTHER"] < w["DRUG"]
    ref = tokenize("antibiotic ki zarurat nahi hai")
    assert cs_wer(ref, tokenize("antibiotic ki zarurat hai"), weights=w)["cs_wer"] > 0.3
