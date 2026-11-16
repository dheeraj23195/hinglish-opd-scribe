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
