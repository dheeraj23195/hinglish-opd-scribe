"""Word error rate with an explicit alignment (needed for severity weighting)."""
from __future__ import annotations

Op = tuple[str, "str | None", "str | None", int]  # (op, ref_tok, hyp_tok, ref_index)


def align(ref: list[str], hyp: list[str], key=None) -> list[Op]:
    """Levenshtein alignment. Returns ops: eq / sub / del / ins.
    `ref_index` is the reference position (for ins: the position it precedes).
    If `key` is given, tokens are compared by key(token) (e.g. phonetic key),
    so spelling variants align as matches instead of shifting the alignment."""
    rk = [key(t) for t in ref] if key else ref
    hk = [key(t) for t in hyp] if key else hyp
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        ri = rk[i - 1]
        row, prev = d[i], d[i - 1]
        for j in range(1, m + 1):
            row[j] = min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + (ri != hk[j - 1]))
    ops: list[Op] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (rk[i - 1] != hk[j - 1]):
            ops.append(("eq" if rk[i - 1] == hk[j - 1] else "sub", ref[i - 1], hyp[j - 1], i - 1))
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            ops.append(("del", ref[i - 1], None, i - 1))
            i -= 1
        else:
            ops.append(("ins", None, hyp[j - 1], i))
            j -= 1
    return ops[::-1]


def wer(ref: list[str], hyp: list[str]) -> float:
    if not ref:
        return float(len(hyp) > 0)
    return sum(op != "eq" for op, *_ in align(ref, hyp)) / len(ref)
