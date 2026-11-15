# Terminology: SNOMED CT, LOINC, FHIR

* **SNOMED CT** codes clinical concepts (symptoms, diagnoses, allergies,
  drug substances). India has been a SNOMED International member since 2014;
  NRCeS (C-DAC Pune) issues free affiliate licences for use within India.
  The full release, India Reference Sets and the India Drug Extension are
  downloaded from MLDS after registration.
* **LOINC** codes vital signs (8310-5 body temperature, 85354-9 BP panel with
  8480-6 / 8462-4, 8867-4 heart rate, 59408-5 SpO2, 1558-6 fasting glucose).
* **FHIR R4** document Bundle shaped like the ABDM *OPConsultRecord*:
  Composition type SNOMED 371530004 "Clinical consultation report",
  `status = preliminary` until a doctor signs.

## Lexicon status

`src/opdscribe/lexicon/*.tsv` has a `code_status` column:

* `verified-web`: checked against a public SNOMED browser / FHIR IG value set
* `recalled`: compiled by the team, not yet checked against the release
* `unverified` with an empty code: concept kept as text only (FHIR allows an
  uncoded CodeableConcept), e.g. amoxicillin+clavulanate, cefixime, ORS

**Before any clinical use, every code must be validated against the SNOMED CT
India release.** Drug substance codes should move to India Drug Extension
product codes.

Pertinent negatives ("khansi nahi hai") are kept as `Condition` resources with
`verificationStatus = refuted`, so "patient denies cough" survives into the
record instead of silently disappearing.
