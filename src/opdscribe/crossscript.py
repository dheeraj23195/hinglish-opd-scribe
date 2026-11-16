"""Cross-script normalisation for real ASR output.

Whisper (language="hi") writes everything it hears in Devanagari, including
English loanwords ("पैरासिटामोल", "टेम्परेचर") and numbers spoken as words
("साढ़े छह सौ" = 650). This module runs before romanisation:

1. Devanagari digits -> ASCII digits
2. Hindi number words -> digits ("एक सौ पचास" -> 150, "डेढ़" -> 1.5)
3. A small map of clinical English loanwords in Devanagari -> Latin
4. `skeleton()`: a consonant-skeleton key used by the lexicon matcher as a
   last-resort fallback, so a drug name spelled in either script still
   matches ("pairaasitaamol" and "paracetamol" both -> "prstml")
"""
from __future__ import annotations

import re

_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

_NUM_1_99 = """एक दो तीन चार पांच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस बीस
इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस छत्तीस
सैंतीस अड़तीस उनतालीस चालीस इकतालीस बयालीस तैंतालीस चवालीस पैंतालीस छियालीस सैंतालीस अड़तालीस उनचास पचास
इक्यावन बावन तिरपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ इकसठ बासठ तिरसठ चौंसठ पैंसठ छियासठ सड़सठ
अड़सठ उनहत्तर सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर छिहत्तर सतहत्तर अठहत्तर उन्यासी अस्सी इक्यासी बयासी
तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी नवासी नब्बे इक्यानबे बानवे तिरानवे चौरानवे पचानवे छियानवे सत्तानवे
अट्ठानवे निन्यानवे""".split()
NUMBERS: dict[str, float] = {w: i + 1 for i, w in enumerate(_NUM_1_99)}
NUMBERS.update({"पाच": 5, "पान्च": 5, "दश": 10, "चौहद": 14, "पचास": 50, "पाँच": 5, "पांच": 5, "छः": 6, "छे": 6, "छै": 6, "नो": 9, "डेढ़": 1.5, "ढाई": 2.5, "आधा": 0.5,
                "बाइस": 22, "चौसठ": 64, "इक्यानवे": 91})
MULT = {"सौ": 100, "सो": 100, "हज़ार": 1000, "हजार": 1000}
SAADHE = {"साढ़े", "साढे"}
AMBIGUOUS = {"दो", "एक", "नौ", "सात", "साठ"}  # also "give", "one/a", "new", ...: convert only in numeric context
UNIT_CONTEXT = {"दिन", "दिनों", "बार", "हफ्ते", "हफ़्ते", "महीने", "साल", "mg", "एमजी", "मिलीग्राम", "गोली", "टैबलेट",
                "पफ", "baar", "din", "hafte", "mahine", "saal", "puff", "tablet", "बाई", "by", "पर्सेंट", "परसेंट"}

LOANWORDS = dict(x.split(":") for x in """
टेम्परेचर:temperature टेंपरेचर:temperature तापमान:temperature बीपी:bp ब्लड:blood प्रेशर:pressure शुगर:sugar पल्स:pulse
ऑक्सीजन:oxygen आक्सीजन:oxygen फास्टिंग:fasting एलर्जी:allergy एलर्जि:allergy रिएक्शन:reaction एमजी:mg मिलीग्राम:mg
टैबलेट:tablet टेबलेट:tablet इनहेलर:inhaler पफ:puff डॉक्टर:doctor डाक्टर:doctor फीवर:fever कफ:cough हेडेक:headache
वायरल:viral इन्फेक्शन:infection इंफेक्शन:infection डायबिटीज:diabetes डायबिटीज़:diabetes थायरॉइड:thyroid थायराइड:thyroid
अस्थमा:asthma डेंगू:dengue टाइफाइड:typhoid माइग्रेन:migraine एसिडिटी:acidity एंटीबायोटिक:antibiotic ओआरएस:ors
बाई:by बाय:by भाय:by परसेंट:percent मिलग्राम:mg मिलग्राम्स:mg मिलीग्राम्स:mg आलर्जी:allergy ऐलर्जी:allergy एलर्जी:allergy
रिएक्शन:reaction रियेक्शन:reaction टैबलेट्स:tablet माइग्रेन:migraine मिग्रेन:migraine फीवर:fever पर्सेंट:percent यूरिन:urine चेस्ट:chest पेन:pain वीकनेस:weakness लूज:loose मोशन:motion
इलेक्ट्रल:electral डोलो:dolo क्रोसिन:crocin पैरासिटामोल:paracetamol पेरासिटामोल:paracetamol अज़िथ्रल:azithral
एज़िथ्राल:azithral अज़िथ्रोमाइसिन:azithromycin एज़िथ्रोमाइसिन:azithromycin अमोक्सिसिलिन:amoxicillin मॉक्स:mox
सेटीरिज़ीन:cetirizine सेट्रिज़िन:cetirizine ओकासेट:okacet मेटफॉर्मिन:metformin ग्लाइकोमेट:glycomet ग्लिमेपिराइड:glimepiride
अम्लोडिपिन:amlodipine एम्लोडिपिन:amlodipine टेल्मा:telma पैंटोप्राज़ोल:pantoprazole पैंटोसिड:pantocid ओंडेम:ondem
अस्थालिन:asthalin मोंटेयर:montair मॉन्टेयर:montair सेप्ट्रान:septran पेनिसिलिन:penicillin ब्रूफेन:brufen
इबुप्रोफेन:ibuprofen एस्पिरिन:aspirin डिस्प्रिन:disprin सल्फा:sulfa निफ्ट्रान:niftran ग्लाइकोमेट:glycomet
""".split())


def _is_num_word(tok: str) -> bool:
    return tok in NUMBERS or tok in MULT or tok in SAADHE


def _parse_number(toks: list[str], i: int) -> tuple[float | None, int]:
    """Parse a Hindi number phrase starting at i. Returns (value, tokens consumed)."""
    j, total, cur, half = i, 0.0, 0.0, False
    if j < len(toks) and toks[j] in SAADHE:
        half, j = True, j + 1
    seen = False
    while j < len(toks):
        t = toks[j]
        if t in NUMBERS:
            cur += NUMBERS[t]; seen = True
        elif t in MULT and (seen or t == "सौ"):  # "सो" (also "sleep") counts only after a number
            cur = (cur or 1) * MULT[t]
            if half:
                cur += 0.5 * MULT[t]; half = False
            total += cur; cur = 0; seen = True
        elif re.fullmatch(r"\d+", t) and not seen:
            cur += float(t); seen = True
        else:
            break
        j += 1
    if not seen:
        return None, 0
    if half:
        cur += 0.5
    return total + cur, j - i


_POSTPOSITIONS = ("से", "में", "मे", "के", "की", "का", "को", "ने", "पे", "पर", "तक", "है", "हैं", "था", "थे")
_VIRAMA = "्"


def _known(dev: str) -> bool:
    from .normalize import phonetic_key, romanize
    k = phonetic_key(romanize(dev))
    return k in _known_keys() or dev in NUMBERS or dev in LOANWORDS or dev in _POSTPOSITIONS


_KNOWN: set[str] | None = None


def _known_keys() -> set[str]:
    global _KNOWN
    if _KNOWN is None:
        from .lexicon import concepts, drugs
        from .normalize import CANON_VOCAB, phonetic_key
        words = set(CANON_VOCAB)
        for c in concepts().values():
            for sf in c.surface_forms:
                words.update(sf.split())
        for d in drugs().values():
            for sf in d.surface_forms:
                words.update(sf.split())
        _KNOWN = {phonetic_key(w) for w in words if len(w) > 1}
    return _KNOWN


def split_fused(token: str) -> list[str]:
    """Whisper often fuses a word and a postposition with a virama
    ("दिन्से" = दिन + से, "बार्लीजिए" = बार + लीजिए). Split at a virama when
    both sides are known words, or the right side is a postposition."""
    if _VIRAMA not in token or not re.fullmatch(r"[\u0900-\u097F]+", token):
        return [token]
    for i, ch in enumerate(token):
        if ch != _VIRAMA or i == 0 or i == len(token) - 1:
            continue
        left, right = token[:i], token[i + 1:]
        if (right in _POSTPOSITIONS or _known(right)) and _known(left):
            return [left] + split_fused(right)
    return [token]


def preprocess(text: str) -> str:
    """Devanagari digits, fused words, number words and loanwords -> ASCII/Latin."""
    text = text.translate(_DEV_DIGITS)
    text = " ".join(p for t in text.split() for p in split_fused(t))
    toks = re.findall(r"[ऀ-ॿ]+|[^\sऀ-ॿ]+", text.replace("।", " । "))
    out: list[str] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if _is_num_word(t):
            val, n = _parse_number(toks, i)
            if val is not None:
                phrase = toks[i:i + n]
                nxt = toks[i + n] if i + n < len(toks) else ""
                prev = out[-1] if out else ""
                numeric_ctx = nxt in UNIT_CONTEXT or prev in UNIT_CONTEXT or bool(re.fullmatch(r"[a-z]+", prev or "x")) and prev in LOANWORDS.values()
                if n > 1 or phrase[0] not in AMBIGUOUS or numeric_ctx:
                    out.append(str(int(val)) if float(val).is_integer() else str(val))
                    i += n
                    continue
        out.append(LOANWORDS.get(t, t))
        i += 1
    return " ".join(out).replace(" । ", "। ")


# ---------------------------------------------------------------------------
# consonant skeleton
# ---------------------------------------------------------------------------
_SKEL_RULES = [
    (r"g(?=[eiy])", "j"),  # English soft g: allergy -> alarjee
    (r"ph", "f"), (r"c(?=[eiy])", "s"), (r"ck", "k"), (r"c", "k"), (r"q", "k"), (r"x", "ks"), (r"z", "j"), (r"w", "v"),
    (r"(?<=[kgtdpbsj])h", ""), (r"h", ""), (r"y", ""), (r"[aeiou]", ""), (r"(.)\1+", r"\1"),
]


def skeleton(romanised: str) -> str:
    s = romanised.lower()
    for pat, rep in _SKEL_RULES:
        s = re.sub(pat, rep, s)
    return s
