# Scoring a scribe by clinical severity, not word error rate

## Why WER is the wrong target

Word error rate counts every wrong word the same. In a Hinglish OPD consult
that is wrong in both directions:

* **It over-penalises harmless variation.** Romanised Hindi has no standard
  spelling. "bukhar / bukhaar", "nahi / nahin", "zarurat / zaroorat" are all
  WER errors, but nothing clinical has changed.
* **It under-penalises dangerous errors.** Dropping the single word "nahi" in
  "antibiotic ki zarurat nahi hai" costs 1 word of WER and reverses the plan.
  A dose slip 650 → 65, or a sound-alike drug swap, is also "one word".

The project's hypothesis is that *ranking ASR systems by WER can pick the more
dangerous system*, and that a severity-aware metric fixes this.

## Two levels

### 1. CS-WER: clinical-severity-weighted error rate (token level)

Each reference token gets a clinical category from the lexicon:

| Category | Examples | Tier | Weight |
|---|---|---|---|
| DRUG | paracetamol, dolo, azithral | critical | 5 |
| NEGATION | nahi, mat, no, not | critical | 5 |
| NUMBER | 650, 5, 140 | critical | 5 |
| ALLERGY | allergy, reaction, penicillin | critical | 5 |
| CLINICAL | bukhar, khansi, sugar, dengue | major | 3 |
| REGIMEN | baar, din, subah, raat, mg | major | 3 |
| OTHER | content words | minor | 1 |
| FILLER / function | haan, achha, ji, hai, se | negligible | 0.2 |

```
CS-WER = Σ cost(edit) / Σ weight(reference tokens)
```

* the alignment is computed on **phonetic keys**, so spelling variants align
  as matches and cost 0 (WER still counts them);
* a substitution costs the higher of the two tokens' weights (a filler turning
  into a drug name is a critical insertion);
* insertions cost the weight of the inserted token's category.

The weights are an **initial proposal**. Phase 2 calibrates them against
clinician ratings: two or more doctors rate a sample of real ASR errors
(no harm / minor / could change management / could cause harm), and we fit the
weights to those ratings.

### 2. Clinical Error Score (concept level)

Run the extractor on the gold note and on the ASR transcript, then diff the
two structured notes:

| Error | Tier |
|---|---|
| negation flip (symptom present ↔ absent) | critical |
| missed / wrong / extra medication | critical |
| dose changed | critical |
| missed allergy | critical |
| missed or hallucinated symptom / diagnosis | major |
| frequency or course duration changed | major |
| vital value changed | major |
| symptom duration changed, missed pertinent negative, missed vital | minor |

Score = 5·critical + 3·major + 1·minor. We report **critical errors per
consult** as the headline number.

## Limitations (stated up front)

* Errors are from a **simulator**, not real ASR yet. The simulator is useful
  precisely because it can hold WER fixed while moving errors between
  categories, but real error distributions must be measured (phase 2).
* CS-WER weights and concept tiers were designed by the team; they encode a
  view of harm that must be checked against clinicians.
* The concept-level score inherits the extractor's blind spots: a fact the
  extractor cannot read on clean text cannot be scored on noisy text.
