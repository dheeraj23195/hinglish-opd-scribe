# Real-ASR benchmark

## Why
The mid-term results used *simulated* ASR errors. This benchmark runs a real
open-source recogniser (Whisper, via faster-whisper) on spoken versions of the
consults and scores the resulting notes against the same gold labels.

## Audio
* Every consult turn is rendered in mixed script (Hindi words in Devanagari,
  English/medical words in Latin: `opdscribe.sim.to_devanagari`) and spoken by
  the macOS Hindi voice (`say`, hi_IN) on a team member's laptop
  (`make_audio.command`; one clip per turn, AAC 48 kbps).
* **Limitation:** synthetic speech is cleaner and more uniform than real
  patients and doctors (no accents, overlaps, coughs, or hesitations). Results
  are an *upper bound* on real-world accuracy; consented role-play recordings
  replace it next.
* Segmentation is oracle (one clip per turn), so diarisation errors are
  excluded; they will be measured separately on real recordings.

## Noise
"OPD babble" (four other speakers' clips mixed at random offsets plus low-level
broadband noise at a fixed speech-to-noise ratio) is implemented (`--snr 20 10 5`)
but **not yet run**: at ~4 s of compute per second of audio for Whisper medium on
2 vCPUs, this round covers clean audio only.

## Models
`faster-whisper` CTranslate2 conversion of Whisper **medium** (769M parameters),
int8 on CPU, `language="hi"`, beam 5, no conditioning on previous text,
temperature fallback on. Evaluated on 28 consults: held-out v1 (8), held-out v2
(12) and 8 synthetic consults (dev). Whisper **base** was tried and is not usable for
Hindi at this size. The normaliser was adjusted using the *synthetic* consults'
transcripts only (dev set); the held-out transcripts were not inspected before scoring.

## Scoring
Whisper writes Hindi in Devanagari (including English loanwords: "पैरासिटामोल").
Reference and hypothesis are both passed through the same normaliser
(Devanagari number words → digits, loanwords → Latin, romanisation, spelling
canonicalisation), then:

* **WER**: on normalised tokens
* **CS-WER**: clinical-severity-weighted, spelling variants forgiven
* **Clinical errors**: the scribe's note from the ASR transcript vs the gold note

## Reproduce
```bash
python scripts/asr_benchmark.py --audio-dir AUDIO_DIR \
  --model models/faster-whisper-medium --snr clean --limit 24
python scripts/asr_benchmark.py --audio-dir AUDIO_DIR --model models/faster-whisper-medium \
  --snr clean --consults data/heldout/heldout_v2.jsonl --limit 12 --tag heldout_v2
```
