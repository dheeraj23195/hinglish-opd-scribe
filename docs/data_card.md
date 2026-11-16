# Data card

## 1. Synthetic Hinglish OPD consults (`data/synthetic/consults.jsonl`)

| | |
|---|---|
| Size | 83 consults, 40 pseudonymous patients, 1–3 visits each |
| Language | Romanised Hindi–English code-mixed (Hinglish), a few Devanagari tokens |
| Scenarios | 12: viral URTI, viral fever, gastroenteritis, UTI, gastritis, dengue, typhoid, pharyngitis, migraine, asthma, type 2 diabetes, hypertension |
| Labels | symptoms (present/absent, duration), history, diagnosis, allergies, medications (dose, frequency, course), vitals, follow-up, expected safety flags |
| Built-in safety cases | antibiotic prescribed for a viral diagnosis; drug conflicting with an allergy told at an earlier visit |
| Generator | `python -m opdscribe.sim.generate` (seeded, reproducible) |

Facts are sampled first and then rendered into dialogue, so the gold label is
exactly what was said. **Limitation:** the rule-based extractor and the
generator share vocabulary, so clean-text accuracy on this set is a sanity
check, not a generalisation result. Use the held-out set for that.

The scripts double as role-play material: team members and consenting
volunteers can read them aloud to create real audio with the same gold labels.

## 2. Held-out hand-written consults (`data/heldout/heldout.jsonl`)

8 consults written by hand in phrasing the extractor was never tuned on:
English negations ("No sir, breathing is fine"), Devanagari sentences, raw
diarisation labels (`spk_0`/`spk_1`), attendants speaking for the patient,
brand names, implicit answers. Scored once, results reported unchanged.

## 3. Held-out v2 (`data/heldout/heldout_v2.jsonl`)

12 consults, 61 gold facts, written after the mid-term and **committed (fa256a5)
before any extractor change**. Adds Indian 1-0-1 dosing notation, a mother
speaking for her child, follow-ups that refer to earlier medicines, English-heavy
and Devanagari-heavy consults, "na X, na Y" negation. Scored once per code
version; numbers in `results/extractor_progress.json`.

## 4. Spoken consults (synthetic speech)

Every turn of the synthetic, held-out v1 and v2 consults (1,562 clips, ~62 min)
rendered in mixed script (`opdscribe.sim.to_devanagari`) and spoken by the macOS
Hindi voice (`make_audio.command`, run on a team laptop). Used for the real-ASR
benchmark (`docs/asr_benchmark.md`). Audio is not committed to the repo; it can
be regenerated from the scripts. Limitation: one clean synthetic voice.

## 5. Clinician rating items (`data/ratings/`)

114 single-error items (one ASR edit each), stratified over 8 clinical
categories, for metric calibration (`docs/clinician_rating_protocol.md`).

## 6. Public datasets planned for phase 2

| Dataset | What it gives us | Notes |
|---|---|---|
| MUCS 2021 Hindi–English code-switching subtask | Real code-switched Hindi–English speech for ASR baselines | ~90 h train; not medical |
| PriMock57 | 57 mock primary-care consults with audio, transcripts and notes | English (UK); gold standard for the note-generation task format |
| Consented role-play recordings (ours) | Real Hinglish OPD audio with our gold labels | Read from the synthetic scripts; consent form + sandbox storage |

No real patient data is used at this stage.

## Privacy

* No names, phone numbers or ABHA numbers anywhere; patient IDs are pseudonyms.
* Phase-2 audio: written consent, stored only in an India-region bucket
  (AWS ap-south-1, Mumbai), deleted after transcription (see `AWSTranscribeASR`).
