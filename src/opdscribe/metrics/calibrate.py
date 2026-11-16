"""Calibrate CS-WER weights against clinician harm ratings.

Workflow (see docs/clinician_rating_protocol.md):

1. `make_items()` samples single, isolated ASR edits (one substitution,
   deletion or insertion applied to an otherwise correct utterance),
   stratified by clinical category.
2. Two or more clinicians rate each item independently on a 0-4 harm scale.
3. `agreement()` reports inter-rater reliability (quadratic-weighted kappa
   for two raters, Krippendorff's alpha (interval) for any number).
4. `fit_weights()` turns ratings into per-category CS-WER weights.

The fitted weights are passed to `cs_wer(..., weights=...)`.
"""
from __future__ import annotations

import random
from collections import defaultdict
from statistics import mean

from ..normalize import tokenize
from .severity import DEFAULT_WEIGHTS, _hyp_cat, tag_tokens
from .wer import align

HARM_SCALE = {
    0: "No effect: meaning unchanged (spelling, filler)",
    1: "Cosmetic: odd wording, a reader would not be misled",
    2: "Needs clarification: a careful reader might be unsure",
    3: "Could change management: wrong but plausible fact in the note",
    4: "Could cause harm: e.g. wrong drug/dose, missed allergy, reversed negation",
}


def make_items(consults: list[dict], corrupt_fn, n_per_category: int = 15, seed: int = 0) -> list[dict]:
    """`corrupt_fn(consult, seed) -> consult` produces ASR-like hypotheses.
    Returns rating items with exactly one edit each."""
    rng = random.Random(seed)
    pool: dict[str, list[dict]] = defaultdict(list)
    for k, c in enumerate(consults):
        h = corrupt_fn(c, k)
        for ti, (rt, ht) in enumerate(zip(c["turns"], h["turns"])):
            ref, hyp = tokenize(rt["text"]), tokenize(ht["text"])
            cats = tag_tokens(ref)
            for op, r, hy, i in align(ref, hyp):
                if op == "eq":
                    continue
                if op == "ins":
                    edited = ref[:i] + [hy] + ref[i:]
                    cat = _hyp_cat(hy)
                elif op == "del":
                    edited = ref[:i] + ref[i + 1:]
                    cat = cats[i]
                else:
                    edited = ref[:i] + [hy] + ref[i + 1:]
                    cat = cats[i]
                pool[cat].append({"consult_id": c["consult_id"], "turn": ti, "speaker": rt["speaker"],
                                  "said": " ".join(ref), "transcribed": " ".join(edited), "op": op,
                                  "ref_token": r or "", "hyp_token": hy or "", "category": cat})
    items: list[dict] = []
    for cat in DEFAULT_WEIGHTS:
        cand = pool.get(cat, [])
        rng.shuffle(cand)
        seen = set()
        for it in cand:
            key = (it["said"], it["transcribed"])
            if key in seen:
                continue
            seen.add(key)
            items.append(it)
            if sum(1 for x in items if x["category"] == cat) >= n_per_category:
                break
    rng.shuffle(items)
    for n, it in enumerate(items, 1):
        it["item_id"] = f"R{n:03d}"
    return items


def agreement(ratings: dict[str, dict[str, float]]) -> dict:
    """ratings: rater -> {item_id: score}. Krippendorff's alpha (interval
    metric) over all raters; quadratic-weighted kappa when there are two."""
    raters = list(ratings)
    items = sorted({i for r in ratings.values() for i in r})
    units = [[ratings[r][i] for r in raters if i in ratings[r]] for i in items]
    units = [u for u in units if len(u) >= 2]
    pairable = [v for u in units for v in u]
    if len(units) < 2 or len(set(pairable)) < 2:
        return {"alpha": None, "n_items": len(units)}
    n = len(pairable)
    do = sum(sum((a - b) ** 2 for a in u for b in u) / (len(u) - 1) for u in units) / n
    de = sum((a - b) ** 2 for a in pairable for b in pairable) / (n * (n - 1))
    out = {"alpha": 1 - do / de if de else None, "n_items": len(units), "n_raters": len(raters)}
    if len(raters) == 2:
        a, b = raters
        common = [i for i in items if i in ratings[a] and i in ratings[b]]
        xs, ys = [ratings[a][i] for i in common], [ratings[b][i] for i in common]
        k = 5
        obs = sum((x - y) ** 2 for x, y in zip(xs, ys)) / len(common)
        exp = sum((x - y) ** 2 for x in xs for y in ys) / (len(common) ** 2)
        out["weighted_kappa"] = 1 - obs / exp if exp else None
        _ = k
    return out


def fit_weights(items: list[dict], ratings: dict[str, dict[str, float]], floor: float = 0.1, scale_to: float = 5.0) -> dict:
    """Per-category weight = mean clinician rating for edits in that category,
    rescaled so the most harmful category gets `scale_to` (default matches
    the current top weight). Categories with no rated items keep defaults."""
    by_cat: dict[str, list[float]] = defaultdict(list)
    for it in items:
        scores = [r[it["item_id"]] for r in ratings.values() if it["item_id"] in r]
        if scores:
            by_cat[it["category"]].append(mean(scores))
    means = {c: mean(v) for c, v in by_cat.items() if v}
    if not means:
        return dict(DEFAULT_WEIGHTS)
    top = max(means.values()) or 1.0
    w = dict(DEFAULT_WEIGHTS)
    for c, m in means.items():
        w[c] = max(floor, round(scale_to * m / top, 3))
    return w
