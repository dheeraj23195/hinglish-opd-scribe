# Clinician rating protocol (metric calibration)

**Goal.** Replace the team's guessed CS-WER weights with weights grounded in how
doctors judge the harm of transcription errors.

## Raters
At least 2 (ideally 3) clinicians who work in Hindi/Hinglish OPDs (MBBS
interns or residents are fine). Raters work independently and do not discuss
items until all ratings are in.

## Material
`data/ratings/rating_sheet_blank.csv`: 114 items (15 per error category,
fewer where rare). Each item shows **what was said** and **what the scribe
wrote**, differing by exactly one word. Categories are hidden from raters.
Import the CSV into Google Sheets or Forms; it takes ~25 minutes.

## Question
> "Suppose a busy doctor signed the note written from *what the scribe wrote*.
> What is the worst plausible consequence for the patient?"

| Score | Meaning |
|---|---|
| 0 | No effect: meaning unchanged (spelling, filler) |
| 1 | Cosmetic: odd wording, a reader would not be misled |
| 2 | Needs clarification: a careful reader might be unsure |
| 3 | Could change management: wrong but plausible fact in the note |
| 4 | Could cause harm: e.g. wrong drug or dose, missed allergy, reversed negation |

## Analysis (`opdscribe.metrics.calibrate`)
1. Agreement: Krippendorff's alpha (interval); quadratic-weighted kappa for two
   raters. Target alpha ≥ 0.67; below that, discuss disagreements and refine
   the scale before fitting.
2. Fit: category weight = mean rating, rescaled so the most harmful category
   gets 5. Re-run every CS-WER experiment with the fitted weights and report
   both versions.

## Ethics
Raters see synthetic role-play text only: no patient data. Record rater
role and years of experience, not names.
