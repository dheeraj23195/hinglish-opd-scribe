"""Smoke test of the Streamlit demo (skipped if streamlit isn't installed)."""
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
APP = str(Path(__file__).resolve().parents[1] / "app" / "app.py")


def test_app_writes_a_note_and_scores_metric():
    at = st_testing.AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    at.button[0].click().run()
    assert not at.exception
    assert any("Paracetamol" in m.value for m in at.markdown)
    assert any("FHIR R4 document bundle validates" in c.value for c in at.caption)
    crit = [m for m in at.metric if m.label == "Critical errors in the note"][0]
    assert int(crit.value) >= 1  # 650 -> 65 dose slip; the dropped "nahi" is caught by CS-WER, not by the note diff
    csw = [m for m in at.metric if m.label == "CS-WER"][0]
    w = [m for m in at.metric if m.label == "WER"][0]
    assert int(csw.value.rstrip("%")) > int(w.value.rstrip("%"))


def test_heldout_example_keeps_speaker_labels_and_flags_antibiotic():
    """Held-out examples use spk_0/spk_1; the app must not turn every line into the patient."""
    import json
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from opdscribe.pipeline import Scribe
    from opdscribe.schema import Turn

    src = (root / "app" / "app.py").read_text(encoding="utf-8")
    ns: dict = {}
    exec(src[src.index("def parse_transcript"): src.index("st.title")], {"Turn": Turn, "json": json}, ns)
    c = next(json.loads(l) for l in (root / "data/heldout/heldout.jsonl").read_text(encoding="utf-8").splitlines() if '"H05"' in l)
    text = ns["to_text"](c)
    assert "spk_1:" in text
    note = Scribe().run(ns["parse_transcript"](text), "H05", "H05", c["date"], save=False).note
    assert "antibiotic_for_viral" in {f.kind for f in note.safety_flags}
    assert any(f.concept_id == "cough" and not f.present for f in note.findings)
