"""Category-aware ASR error simulator.

Lets us create ASR outputs with *controlled* error profiles, e.g. two
systems with the same WER where one only garbles filler words and the
other drops negations and drug names. That is exactly the situation in
which WER and clinical harm disagree, and it is what the metric must
detect. Real-audio evaluation replaces this in phase 2.

Error types per token category:
* DRUG      -> another drug name (wrong drug) or an unrecognisable garble
* NUMBER    -> plausible digit slip (650->65, 5->15) or deletion
* NEGATION  -> deletion (meaning flips) or substitution
* CLINICAL  -> garble or deletion
* others    -> deletion or substitution with a filler
* variant   -> romanisation spelling variant (bukhar->bukhaar), meaning-preserving
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..lexicon import drugs
from ..metrics.severity import tag_tokens
from ..normalize import phonetic_key, tokenize

FILLER_POOL = ["haan", "achha", "toh", "ji", "hmm", "matlab", "na"]
REGIMEN_POOL = ["baar", "din", "subah", "shaam", "raat", "hafte", "liye"]


@dataclass
class NoiseProfile:
    name: str
    p: dict[str, float]  # per-category error probability
    p_variant: float = 0.0  # spelling-variant probability for other alphabetic tokens
    p_insert: float = 0.0  # filler insertion probability after each token
    meta: dict = field(default_factory=dict)


def _garble(tok: str, rng: random.Random) -> str:
    if len(tok) <= 3:
        return tok + rng.choice("aeiou")
    i = rng.randrange(1, len(tok) - 1)
    out = tok[:i] + tok[i + 2:] + rng.choice(["a", "e", "ar", "in"])
    return out if phonetic_key(out) != phonetic_key(tok) else out + "x"


def _variant(tok: str, rng: random.Random) -> str:
    ops = []
    for v, vv in (("a", "aa"), ("i", "ee"), ("u", "oo")):
        if v in tok and vv not in tok:
            ops.append(lambda t, v=v, vv=vv: t.replace(v, vv, 1))
    if tok.endswith("i"):
        ops.append(lambda t: t + "n")
    if "kh" in tok:
        ops.append(lambda t: t.replace("kh", "k", 1))
    if "w" in tok:
        ops.append(lambda t: t.replace("w", "v", 1))
    if not ops:
        return tok
    out = rng.choice(ops)(tok)
    return out if phonetic_key(out) == phonetic_key(tok) else tok


def _number_slip(tok: str, rng: random.Random) -> str:
    v = tok.split(".")[0]
    choices = [v[:-1] or "1", v + "0", "1" + v, str(int(v) + rng.choice([-10, 10, 1, -1, 100]))]
    return rng.choice([c for c in choices if c != tok and c.lstrip("-")])


def corrupt_tokens(tokens: list[str], prof: NoiseProfile, rng: random.Random) -> list[str]:
    cats = tag_tokens(tokens)
    drug_surfaces = [sf for d in drugs().values() for sf in d.surface_forms if " " not in sf and len(sf) > 3]
    out: list[str] = []
    for tok, cat in zip(tokens, cats):
        if rng.random() < prof.p.get(cat, 0.0):
            if cat == "DRUG":
                out.append(rng.choice(drug_surfaces) if rng.random() < 0.5 else _garble(tok, rng))
            elif cat == "NUMBER":
                if rng.random() < 0.7:
                    out.append(_number_slip(tok, rng))
            elif cat == "NEGATION":
                if rng.random() < 0.3:
                    out.append(rng.choice(["hi", "to"]))
            elif cat in ("CLINICAL", "ALLERGY"):
                if rng.random() < 0.6:
                    out.append(_garble(tok, rng))
            elif cat == "REGIMEN":
                if rng.random() < 0.5:
                    out.append(rng.choice([r for r in REGIMEN_POOL if r != tok]))
            else:
                if rng.random() < 0.5:
                    out.append(rng.choice(FILLER_POOL))
        elif cat in ("OTHER", "FILLER", "CLINICAL", "REGIMEN") and tok.isalpha() and rng.random() < prof.p_variant:
            out.append(_variant(tok, rng))
        else:
            out.append(tok)
        if rng.random() < prof.p_insert:
            out.append(rng.choice(FILLER_POOL))
    return out


def corrupt_consult(consult: dict, prof: NoiseProfile, seed: int) -> dict:
    """Returns a copy of the consult with each turn's text replaced by
    simulated ASR output (lower-cased, unpunctuated, like most ASR)."""
    rng = random.Random(seed)
    turns = [{"speaker": t["speaker"], "text": " ".join(corrupt_tokens(tokenize(t["text"]), prof, rng))} for t in consult["turns"]]
    return {**consult, "turns": turns}


# Three illustrative systems with deliberately different error *profiles*.
SYSTEMS = [
    NoiseProfile("A: spelling-noisy", {"FILLER": 0.30, "OTHER": 0.12, "REGIMEN": 0.02, "CLINICAL": 0.01}, p_variant=0.45, p_insert=0.05),
    NoiseProfile("B: clinically brittle", {"DRUG": 0.25, "NUMBER": 0.20, "NEGATION": 0.30, "ALLERGY": 0.20, "CLINICAL": 0.06,
                                           "REGIMEN": 0.04, "OTHER": 0.02, "FILLER": 0.02}),
    NoiseProfile("C: uniform", {k: 0.10 for k in ("DRUG", "NUMBER", "NEGATION", "ALLERGY", "CLINICAL", "REGIMEN", "OTHER", "FILLER")},
                 p_variant=0.10, p_insert=0.02),
]


def random_profile(rng: random.Random, i: int) -> NoiseProfile:
    cats = ("DRUG", "NUMBER", "NEGATION", "ALLERGY", "CLINICAL", "REGIMEN", "OTHER", "FILLER")
    return NoiseProfile(f"rand{i}", {c: rng.uniform(0, 0.35) ** 1.3 for c in cats}, p_variant=rng.uniform(0, 0.4), p_insert=rng.uniform(0, 0.05))
