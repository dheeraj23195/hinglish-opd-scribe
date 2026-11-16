"""Terminology lexicons: Hinglish surface forms -> internal concept -> SNOMED CT.

The TSV files are deliberately small and human-editable so that clinicians
on the team can review and extend them. SNOMED CT codes were compiled by the
team and are marked `code_status` = recalled | unverified; every code must be
checked against the SNOMED CT India release (free under the NRCeS affiliate
licence) before any clinical use. See docs/terminology.md.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Optional

from ..normalize import normalize_text, phonetic_key

# words skipped inside multi-word clinical phrases ("gala bahut kharab")
INTENSIFIERS = {"bahut", "thoda", "zyada", "kaafi", "bilkul", "poora", "poore", "pura", "halka", "tez", "sa", "si", "bhi"}


@dataclass(frozen=True)
class Concept:
    concept_id: str
    category: str
    preferred_term: str
    snomed_code: str
    code_status: str
    surface_forms: tuple[str, ...]


@dataclass(frozen=True)
class Drug:
    drug_id: str
    generic: str
    snomed_code: str
    drug_class: str
    is_antibiotic: bool
    aware_group: str  # WHO AWaRe: Access / Watch / Reserve
    code_status: str
    surface_forms: tuple[str, ...]


def _read_tsv(name: str) -> list[dict]:
    with resources.files(__package__).joinpath(name).open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


@lru_cache(maxsize=1)
def concepts() -> dict[str, Concept]:
    out = {}
    for r in _read_tsv("concepts.tsv"):
        out[r["concept_id"]] = Concept(
            r["concept_id"], r["category"], r["preferred_term"], r["snomed_code"], r["code_status"],
            tuple(s.strip() for s in r["surface_forms"].split("|") if s.strip()),
        )
    return out


@lru_cache(maxsize=1)
def drugs() -> dict[str, Drug]:
    out = {}
    for r in _read_tsv("drugs.tsv"):
        out[r["drug_id"]] = Drug(
            r["drug_id"], r["generic"], r["snomed_substance_code"], r["drug_class"], r["is_antibiotic"] == "1",
            r["aware_group"], r["code_status"], tuple(s.strip() for s in r["surface_forms"].split("|") if s.strip()),
        )
    return out


@dataclass
class Match:
    start: int  # token index, inclusive
    end: int  # token index, exclusive
    kind: str  # "concept" | "drug"
    ref_id: str
    category: str  # symptom / condition / allergy / drug


@dataclass
class Matcher:
    """Longest-match-first phrase matcher over phonetic keys.

    `use_phonetic=False` gives exact string matching (used as an ablation)."""

    use_phonetic: bool = True
    fuzzy_drugs: bool = True
    _index: dict[tuple[str, ...], list[tuple[str, str, str]]] = field(default_factory=dict)
    _max_len: int = 1

    def __post_init__(self) -> None:
        for c in concepts().values():
            for sf in c.surface_forms:
                self._add(sf, "concept", c.concept_id, c.category)
        for d in drugs().values():
            for sf in d.surface_forms:
                self._add(sf, "drug", d.drug_id, "drug")
        self._drug_keys = {k: v for k, v in self._index.items() if len(k) == 1 and v[0][0] == "drug"}
        # consonant-skeleton index for cross-script fallback (unique skeletons only)
        from ..crossscript import skeleton
        sk: dict[str, set] = {}
        for k, v in self._index.items():
            if len(k) == 1 and v[0][2] in ("drug", "symptom", "condition"):
                for sf in (drugs()[v[0][1]].surface_forms if v[0][0] == "drug" else concepts()[v[0][1]].surface_forms):
                    if " " not in sf and sf.isascii() and len(skeleton(sf)) >= 4:
                        sk.setdefault(skeleton(sf), set()).add(v[0])
        self._skel = {s: next(iter(v)) for s, v in sk.items() if len(v) == 1}
        self._skeleton = skeleton

    def key(self, tok: str) -> str:
        return phonetic_key(tok) if self.use_phonetic else tok

    def _add(self, surface: str, kind: str, ref_id: str, category: str) -> None:
        toks = normalize_text(surface)
        variants = {tuple(self.key(t) for t in toks)}
        stripped = [t for t in toks if t not in INTENSIFIERS]
        if stripped and len(stripped) < len(toks):  # "zyada pyaas" is also indexed as "pyaas"
            variants.add(tuple(self.key(t) for t in stripped))
        for k in variants:
            if k and (kind, ref_id, category) not in self._index.get(k, []):
                self._index.setdefault(k, []).append((kind, ref_id, category))
                self._max_len = max(self._max_len, len(k))

    def find(self, tokens: list[str], categories: Optional[set[str]] = None) -> list[Match]:
        keys = [self.key(t) for t in tokens]
        out: list[Match] = []
        i = 0
        while i < len(keys):
            hit = None
            for n in range(min(self._max_len, len(keys) - i), 0, -1):
                cands = self._index.get(tuple(keys[i:i + n]))
                if cands:
                    cands = [c for c in cands if categories is None or c[2] in categories]
                    if cands:
                        hit = (n, cands[0])
                        break
            if hit is None and self.fuzzy_drugs and (categories is None or "drug" in categories):
                hit = self._fuzzy_drug(keys[i])
            if hit is None and self.use_phonetic and len(tokens[i]) >= 6:
                cand = self._skel.get(self._skeleton(tokens[i]))
                if cand and (categories is None or cand[2] in categories):
                    hit = (1, cand)
            if hit:
                n, (kind, ref_id, cat) = hit
                out.append(Match(i, i + n, kind, ref_id, cat))
                i += n
            else:
                i += 1
        return out

    def _fuzzy_drug(self, k: str):
        if len(k) < 6:
            return None
        best = None
        for dk, v in self._drug_keys.items():
            if abs(len(dk[0]) - len(k)) <= 1 and _edit_distance(dk[0], k) <= 1:
                best = (1, v[0])
                break
        return best


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]
