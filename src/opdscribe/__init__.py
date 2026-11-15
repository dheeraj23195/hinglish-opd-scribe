"""opdscribe: open-source Hinglish OPD scribe.

consult (audio / transcript) -> clinical facts -> SNOMED CT codes -> FHIR R4
document, with longitudinal patient memory and clinical-severity evaluation.
"""
from .pipeline import Scribe, ScribeResult
from .schema import ClinicalNote, Turn

__version__ = "0.1.0"
__all__ = ["Scribe", "ScribeResult", "ClinicalNote", "Turn"]
