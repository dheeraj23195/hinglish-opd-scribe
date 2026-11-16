"""Hinglish text normalisation.

Romanised Hindi has no standard spelling: the same word comes out of
ASR systems as "bukhar", "bukhaar" or "bukhār"; "nahi", "nahin", "nai".
Plain WER counts every one of these as an error even though nothing
clinical changed. This module provides

* `tokenize`        – lower-case, strip punctuation, keep Devanagari
* `romanize`        – light Devanagari -> Hinglish romaniser (for ASR that outputs script)
* `phonetic_key`    – a spelling-variant-insensitive key used for matching
* `words_to_digits` – Hindi/English number words -> digits (only before units,
                      because "do" also means "give")
"""
from __future__ import annotations

import re
import unicodedata

_PUNCT = re.compile(r"[^\wऀ-ॿ\s/.]")


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text.lower())
    text = text.replace("।", " ")
    # Indian prescription notation morning-noon-night, e.g. 1-0-1 -> "dose_101"
    text = re.sub(r"\b([0-2])\s*-\s*([0-2])\s*-\s*([0-2])\b", r" dose_\1\2\3 ", text)
    text = _PUNCT.sub(" ", text)
    # keep decimals like 101.5 and ratios like 140/90, drop other dots
    text = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", text)
    text = re.sub(r"(\d)/(\d)", r"\1 / \2", text)
    return [t for t in text.split() if t]


# ---------------------------------------------------------------------------
# Devanagari -> Hinglish romanisation (simple, table-based, with final-schwa
# deletion). Good enough to map ASR script output onto the lexicon; not a
# linguistically complete transliterator.
# ---------------------------------------------------------------------------
_CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh",
    "ञ": "n", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d",
    "ध": "dh", "न": "n", "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r",
    "ल": "l", "व": "v", "श": "sh", "ष": "sh", "स": "s", "ह": "h", "क़": "q", "ख़": "kh", "ग़": "g",
    "ज़": "z", "ड़": "d", "ढ़": "rh", "फ़": "f",
}
_VOWELS = {"ऑ": "o", "ऍ": "e", "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऋ": "ri"}
_MATRAS = {"ॉ": "o", "ॅ": "e", "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ृ": "ri"}
_SIGNS = {"ं": "n", "ँ": "n", "ः": "h"}
_VIRAMA = "्"
_NUKTA = "़"


def romanize(text: str) -> str:
    out: list[str] = []
    for word in text.split():
        if not re.search(r"[ऀ-ॿ]", word):
            out.append(word)
            continue
        word = unicodedata.normalize("NFC", word)
        buf = ""
        i = 0
        while i < len(word):
            ch = word[i]
            if i + 1 < len(word) and word[i + 1] == _NUKTA:
                ch = ch + _NUKTA
                i += 1
            nxt = word[i + 1] if i + 1 < len(word) else ""
            if ch in _CONS:
                buf += _CONS[ch]
                if nxt in _MATRAS or nxt == _VIRAMA:
                    pass
                else:
                    buf += "a"  # inherent schwa (trimmed at word end below)
            elif ch in _MATRAS:
                buf += _MATRAS[ch]
            elif ch in _VOWELS:
                buf += _VOWELS[ch]
            elif ch in _SIGNS:
                buf += _SIGNS[ch]
            elif ch == _VIRAMA:
                pass
            else:
                buf += ch
            i += 1
        if len(buf) > 2 and buf.endswith("a") and not buf.endswith("aa"):
            buf = buf[:-1]  # schwa deletion: "bukhaara" -> "bukhaar"
        out.append(buf)
    return " ".join(out)


# ---------------------------------------------------------------------------
# Phonetic key: collapses the common romanisation variants.
# ---------------------------------------------------------------------------
_KEY_RULES = [
    (r"chchh|chch", "ch"),  # achchhaa -> achha
    (r"chh", "ch"),
    (r"aa+", "a"), (r"ee+", "i"), (r"ii+", "i"), (r"oo+", "u"), (r"uu+", "u"),
    (r"w", "v"), (r"z", "j"), (r"ph", "f"), (r"q", "k"), (r"ck", "k"),
    (r"(?<=[kgcjtdpbs])h", ""),  # aspiration: kh->k, ch->c, th->t, sh->s
    (r"(?<=[aeiou])h(?=[aeiou])", ""),  # nahi -> nai
    (r"y(?=[^aeiou]|$)", "i"),
    (r"(.)\1+", r"\1"),  # doubled letters
    (r"(?<=[aeiou])n$", ""),  # nasal ending: nahin -> nahi
    (r"ie$", "iye"),  # Devanagari-romanised imperatives: lie -> liye, leejie -> lijiye
]


def phonetic_key(token: str) -> str:
    t = romanize(token.lower())
    if t == "men":  # Devanagari "में" romanises to "men"
        t = "mein"
    for pat, rep in _KEY_RULES:
        t = re.sub(pat, rep, t)
    return t


# ---------------------------------------------------------------------------
# Number words
# ---------------------------------------------------------------------------
NUMBER_WORDS = {
    "ek": 1, "one": 1, "do": 2, "two": 2, "teen": 3, "three": 3, "char": 4, "chaar": 4, "four": 4,
    "paanch": 5, "panch": 5, "five": 5, "chhe": 6, "chhah": 6, "six": 6, "saat": 7, "seven": 7,
    "aath": 8, "eight": 8, "nau": 9, "nine": 9, "das": 10, "ten": 10, "pandrah": 15, "bees": 20,
    "aadha": 0.5, "dedh": 1.5, "dhai": 2.5,
}
UNIT_WORDS = {
    "din", "dino", "dinon", "day", "days", "hafte", "hafta", "hafton", "week", "weeks", "mahine", "mahina",
    "month", "months", "saal", "year", "years", "baar", "bar", "times", "tablet", "tablets", "goli", "golia",
    "puff", "puffs", "chammach", "spoon",
}


def words_to_digits(tokens: list[str]) -> list[str]:
    """Convert number words to digits only when followed by a unit word."""
    out = list(tokens)
    for i, tok in enumerate(tokens[:-1]):
        if tok in NUMBER_WORDS and tokens[i + 1] in UNIT_WORDS:
            v = NUMBER_WORDS[tok]
            out[i] = str(int(v)) if float(v).is_integer() else str(v)
    return out


# Function words the extraction rules depend on. ASR spelling variants of
# these ("deen", "zaroorat", "kyaa") are mapped back to one canonical form.
CANON_VOCAB = """
nahi mat haan ji yes bilkul lekin par magar aur bas sirf kya kab kitne kitna kaisa kaise koi kisi
allergy reaction suit dawai karti karta din dino hafte hafta mahine mahina saal baar roz subah dopahar shaam
raat sone se pehle zarurat pade padne ho jab ke ki liye tak baad dikhaiye dikhana aaiye aana milte lijiye lena
hai paani aaraam kal parson mujhe temperature pulse oxygen fasting sugar bp by mg puff bhi thoda
ek do teen chaar paanch chhe saat aath nau das hafton mein main tablet inhaler
""".split()


def _build_canon() -> dict[str, str]:
    seen: dict[str, set[str]] = {}
    for w in CANON_VOCAB:
        seen.setdefault(phonetic_key(w), set()).add(w)
    # keep only unambiguous keys, and never remap a word that is itself canonical
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


_CANON: dict[str, str] | None = None


def canonicalize(tokens: list[str]) -> list[str]:
    global _CANON
    if _CANON is None:
        _CANON = _build_canon()
    canon_set = set(CANON_VOCAB)
    return [t if t in canon_set else _CANON.get(phonetic_key(t), t) for t in tokens]


def normalize_text(text: str, canonical: bool = True) -> list[str]:
    """Full normalisation used before matching: Devanagari numbers/loanwords,
    romanise, tokenise, canonicalise spelling variants of function words,
    number words -> digits."""
    if re.search(r"[\u0900-\u097F]", text):
        from .crossscript import preprocess
        text = preprocess(text)
    toks = tokenize(romanize(text))
    if canonical:
        toks = canonicalize(toks)
    return words_to_digits(toks)
