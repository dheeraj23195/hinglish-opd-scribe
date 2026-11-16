"""Interactive demo: streamlit run app/app.py

Tab 1  Scribe: paste a Hinglish consult (or pick an example) -> SOAP note,
       SNOMED/LOINC-coded facts with evidence, safety flags, FHIR bundle.
       Visits are remembered per patient ID for the session's lifetime.
Tab 2  Metric playground: what was said vs what ASR heard -> WER, CS-WER
       and the clinical errors it causes in the note.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# After a hot redeploy Streamlit re-runs this file but keeps already-imported
# opdscribe modules (they live outside app/) and the cached Scribe. Drop both
# if they predate the current code so the app never mixes old and new.
import opdscribe.memory as _mem  # noqa: E402

if not hasattr(_mem.PatientMemory, "visits"):
    for _k in [k for k in sys.modules if k == "opdscribe" or k.startswith("opdscribe.")]:
        del sys.modules[_k]
    st.cache_resource.clear()
    st.cache_data.clear()

from opdscribe import fhir  # noqa: E402
from opdscribe.extract import extract  # noqa: E402
from opdscribe.lexicon import concepts, drugs  # noqa: E402
from opdscribe.memory import PatientMemory  # noqa: E402
from opdscribe.metrics import clinical_error_score, compare_notes, cs_wer, wer  # noqa: E402
from opdscribe.normalize import normalize_text  # noqa: E402
from opdscribe.pipeline import Scribe  # noqa: E402
from opdscribe.schema import Turn  # noqa: E402

st.set_page_config(page_title="Hinglish OPD scribe", page_icon="🩺", layout="wide")


@st.cache_resource
def get_scribe() -> Scribe:
    return Scribe(PatientMemory())  # in-memory: forgotten when the app restarts


@st.cache_data
def examples() -> dict[str, dict]:
    out = {}
    for f in ("data/heldout/heldout.jsonl", "data/heldout/heldout_v2.jsonl", "data/synthetic/consults.jsonl"):
        for line in (ROOT / f).read_text(encoding="utf-8").splitlines()[:12]:
            c = json.loads(line)
            out[f"{c['consult_id']} · {c['scenario']}"] = c
    return out


def parse_transcript(text: str) -> list[Turn]:
    """Lines like 'D: ...' / 'P: ...' (or 'doctor:' / 'patient:'); unlabeled lines alternate."""
    turns, last = [], "patient"
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        head, _, rest = line.partition(":")
        h = head.strip().lower()
        if rest and h in {"d", "dr", "doctor", "doc"}:
            turns.append(Turn("doctor", rest.strip()))
        elif rest and h in {"p", "patient", "pt", "a", "attendant"}:
            turns.append(Turn("patient", rest.strip()))
        elif rest and h.startswith("spk"):
            turns.append(Turn(h, rest.strip()))
        else:
            last = "doctor" if last == "patient" else "patient"
            turns.append(Turn(last, line))
    return turns


def to_text(c: dict) -> str:
    tag = {"doctor": "D", "patient": "P"}
    # Held-out consults use diarisation labels (spk_0/spk_1); keep them so the
    # pipeline infers who is the doctor instead of treating every line as patient.
    return "\n".join(f"{tag.get(t['speaker'], t['speaker'])}: {t['text']}" for t in c["turns"])


st.title("🩺 Hinglish OPD scribe")
st.caption("Research prototype: AI draft notes for clinician review. Synthetic data only; codes pending SNOMED CT India validation.")
tab1, tab2 = st.tabs(["Scribe a consult", "Metric playground"])

with tab1:
    ex = examples()
    c1, c2, c3 = st.columns([2, 1, 1])
    choice = c1.selectbox("Load an example", ["(type your own)"] + list(ex))
    pid = c2.text_input("Patient ID (pseudonym)", value=ex[choice]["patient_id"] if choice in ex else "DEMO-1")
    date = c3.text_input("Visit date", value=ex[choice]["date"] if choice in ex else "2026-11-16")
    default = to_text(ex[choice]) if choice in ex else "P: Teen din se bukhar hai aur khansi bhi.\nD: Saans lene mein dikkat hai kya?\nP: Nahi ji.\nD: Kisi dawai se allergy?\nP: Haan, penicillin se.\nD: Temperature 101 hai. Viral fever lag raha hai. Dolo 650 din mein teen baar, teen din ke liye."
    text = st.text_area("Transcript (one turn per line: `D:` doctor, `P:` patient; Roman or Devanagari)", value=default, height=240)
    if st.button("Write the note", type="primary"):
        scribe = get_scribe()
        res = scribe.run(parse_transcript(text), pid, f"{pid}-{date}", date)
        note = res.note
        left, right = st.columns([3, 2])
        with left:
            st.markdown(res.markdown)
        with right:
            if note.safety_flags:
                st.subheader("Safety flags")
                for f in note.safety_flags:
                    (st.error if f.severity == "critical" else st.warning if f.severity == "major" else st.info)(f"**{f.severity.upper()}**: {f.message}")
            else:
                st.success("No safety flags")
            if res.reconciliation:
                st.subheader("Since last visit")
                st.json(res.reconciliation)
        cdb, ddb = concepts(), drugs()
        rows = [{"type": "diagnosis" if f.is_diagnosis else f.category, "concept": cdb[f.concept_id].preferred_term,
                 "SNOMED CT": cdb[f.concept_id].snomed_code, "status": "present" if f.present else "denied",
                 "duration (d)": f.duration_days, "evidence": f.evidence} for f in note.findings]
        rows += [{"type": "allergy", "concept": cdb[a.concept_id].preferred_term, "SNOMED CT": cdb[a.concept_id].snomed_code,
                  "status": "", "duration (d)": None, "evidence": a.evidence} for a in note.allergies]
        rows += [{"type": "medication", "concept": f"{ddb[m.drug_id].generic} {m.dose_value or ''} {m.dose_unit or ''} {m.frequency or ''}".strip(),
                  "SNOMED CT": ddb[m.drug_id].snomed_code or "(text only)", "status": f"course {m.duration_days:g} d" if m.duration_days else "",
                  "duration (d)": None, "evidence": m.evidence} for m in note.medications]
        st.subheader("Extracted facts, with codes and evidence")
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        try:
            fhir.validate(res.fhir_bundle)
            st.caption(f"✅ FHIR R4 document bundle validates ({len(res.fhir_bundle['entry'])} resources)")
        except Exception as e:  # pragma: no cover
            st.caption(f"⚠️ FHIR validation: {e}")
        with st.expander("FHIR bundle (JSON)"):
            st.json(res.fhir_bundle)
        st.download_button("Download FHIR JSON", json.dumps(res.fhir_bundle, indent=2, ensure_ascii=False), file_name=f"{pid}-{date}.fhir.json")
    with st.expander("Visits remembered this session"):
        mem = get_scribe().memory
        st.write([{"patient": r[0], "date": r[1]} for r in mem.visits()])

with tab2:
    st.markdown("Change one word and compare what **WER** says with what happens to the **note**.")
    a, b = st.columns(2)
    said = a.text_area("What was said", "Antibiotic ki zarurat nahi hai. Dolo 650 din mein teen baar lijiye.", height=120)
    heard = b.text_area("What the ASR heard", "Antibiotic ki zarurat hai. Dolo 65 din mein teen baar lijiye.", height=120)
    rt, ht = normalize_text(said), normalize_text(heard)
    cw = cs_wer(rt, ht)
    E = compare_notes(extract([Turn("doctor", said)]), extract([Turn("doctor", heard)]))
    s = clinical_error_score(E)
    m1, m2, m3 = st.columns(3)
    m1.metric("WER", f"{wer(rt, ht):.0%}")
    m2.metric("CS-WER", f"{cw['cs_wer']:.0%}", help="clinical-severity-weighted; spelling variants forgiven")
    m3.metric("Critical errors in the note", s["critical"])
    if E:
        st.table(pd.DataFrame([{"severity": e.severity, "error": e.kind.replace("_", " "), "detail": e.detail} for e in E]))
    st.caption(f"Spelling variants forgiven by CS-WER: {cw['n_variant_forgiven']}")
