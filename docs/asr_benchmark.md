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
"OPD babble": four other speakers' clips mixed at random offsets plus low-level
broadband noise, added at a fixed speech-to-noise ratio (20, 10, 5 dB).

## Models
`faster-whisper` CTranslate2 conversions of Whisper **base** (74M parameters) and
**medium** (769M), int8 on CPU, `language="hi"`, beam 5, no conditioning on
previous text. Medium runs at ~4 s of compute per second of audio on 2 vCPUs,
so it is evaluated on a 24-consult subset (8 held-out + 16 synthetic).

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
  --model models/faster-whisper-medium --model models/faster-whisper-base \
  --snr clean 20 10 5 --limit 24
```
