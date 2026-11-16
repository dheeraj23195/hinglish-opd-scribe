"""Analyse the real-ASR benchmark (run scripts/asr_benchmark.py first).

For each consult with a complete ASR transcript:
  WER, CS-WER                (normalised reference vs ASR text)
  asr_*   clinical errors     note(ASR text) vs note(clean text): errors the ASR introduced
  gold_*  clinical errors     note(ASR text) vs gold labels: what a doctor would actually get
Then Spearman correlations (WER / CS-WER vs ASR-induced clinical error score)
and a table of real critical errors with the words behind them.

    python scripts/analyze_asr.py --cache results/asr/cache_faster-whisper-medium_clean.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opdscribe.extract import extract  # noqa: E402
from opdscribe.metrics import clinical_error_score, compare_notes, cs_wer, wer  # noqa: E402
from opdscribe.normalize import normalize_text  # noqa: E402
from opdscribe.schema import Turn  # noqa: E402
from opdscribe.sim.gold import gold_note, turns_of  # noqa: E402

SETS = {"heldout_v1": "data/heldout/heldout.jsonl", "heldout_v2": "data/heldout/heldout_v2.jsonl", "synthetic_dev": "data/synthetic/consults.jsonl"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(ROOT / "results/asr/cache_faster-whisper-medium_clean.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "results/asr"))
    a = ap.parse_args()
    hyp = {}
    for line in Path(a.cache).read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            hyp[d["id"]] = d["text"]
    rows, examples = [], []
    for set_name, path in SETS.items():
        for line in (ROOT / path).read_text(encoding="utf-8").splitlines():
            c = json.loads(line)
            ids = [f"{c['consult_id']}_{i:02d}" for i in range(len(c["turns"]))]
            if not all(t in hyp for t in ids):
                continue
            ref_tok = [t for tt in c["turns"] for t in normalize_text(tt["text"])]
            hyp_tok = [t for t in ids for t in normalize_text(hyp[t])]
            hyp_turns = [Turn(tt["speaker"], hyp[t]) for tt, t in zip(c["turns"], ids)]
            note_asr, note_txt = extract(hyp_turns), extract(turns_of(c))
            e_asr = compare_notes(note_txt, note_asr)
            e_gold = compare_notes(gold_note(c), note_asr)
            e_txt = compare_notes(gold_note(c), note_txt)
            s_asr, s_gold, s_txt = clinical_error_score(e_asr), clinical_error_score(e_gold), clinical_error_score(e_txt)
            cw = cs_wer(ref_tok, hyp_tok)
            rows.append({"set": set_name, "consult_id": c["consult_id"], "n_tokens": len(ref_tok), "wer": wer(ref_tok, hyp_tok),
                         "cs_wer": cw["cs_wer"], "variants_forgiven": cw["n_variant_forgiven"],
                         **{f"asr_{k}": v for k, v in s_asr.items()}, **{f"gold_{k}": v for k, v in s_gold.items()},
                         **{f"text_{k}": v for k, v in s_txt.items()}})
            for e in e_asr:
                if e.severity == "critical":
                    examples.append({"consult_id": c["consult_id"], "set": set_name, "error": e.kind, "detail": e.detail})
    from scipy.stats import spearmanr

    out = {}
    for name in ("all", *SETS):
        R = [r for r in rows if name == "all" or r["set"] == name]
        if not R:
            continue
        m = lambda k: float(np.mean([r[k] for r in R]))  # noqa: E731
        out[name] = {"n_consults": len(R), "wer": m("wer"), "cs_wer": m("cs_wer"),
                     "asr_critical_per_consult": m("asr_critical"), "asr_major_per_consult": m("asr_major"),
                     "asr_score_per_consult": m("asr_score"), "pct_consults_asr_critical": 100 * float(np.mean([r["asr_critical"] > 0 for r in R])),
                     "gold_critical_per_consult": m("gold_critical"), "gold_major_per_consult": m("gold_major"),
                     "text_critical_per_consult": m("text_critical"), "text_major_per_consult": m("text_major")}
    R = rows
    rw = spearmanr([r["wer"] for r in R], [r["asr_score"] for r in R])
    rc = spearmanr([r["cs_wer"] for r in R], [r["asr_score"] for r in R])
    rwk = spearmanr([r["wer"] for r in R], [r["asr_critical"] for r in R])
    rck = spearmanr([r["cs_wer"] for r in R], [r["asr_critical"] for r in R])
    out["correlation"] = {"n": len(R), "wer_vs_asr_score": [float(rw.statistic), float(rw.pvalue)],
                          "cswer_vs_asr_score": [float(rc.statistic), float(rc.pvalue)],
                          "wer_vs_asr_critical": [float(rwk.statistic), float(rwk.pvalue)],
                          "cswer_vs_asr_critical": [float(rck.statistic), float(rck.pvalue)]}
    o = Path(a.out)
    o.mkdir(parents=True, exist_ok=True)
    (o / "asr_analysis.json").write_text(json.dumps({"summary": out, "per_consult": rows, "critical_examples": examples}, indent=1, ensure_ascii=False))
    print(json.dumps(out, indent=1))
    print(f"{len(examples)} ASR-induced critical errors, e.g.:")
    for e in examples[:12]:
        print("  ", e)
    figure(rows, out["correlation"], o / "fig3_real_asr.png")


def figure(rows, corr, path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker  # noqa: F401

    INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    COL = {"heldout_v1": "#2a78d6", "heldout_v2": "#eb6834", "synthetic_dev": "#1baf7a"}
    LAB = {"heldout_v1": "held-out v1", "heldout_v2": "held-out v2", "synthetic_dev": "synthetic (dev)"}
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                         "xtick.color": INK2, "ytick.color": INK2, "figure.facecolor": SURF, "axes.facecolor": SURF})
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True)
    for ax, key, label, r in ((axes[0], "wer", "Word error rate", corr["wer_vs_asr_score"]),
                              (axes[1], "cs_wer", "Clinical-severity WER", corr["cswer_vs_asr_score"])):
        for s, col in COL.items():
            pts = [x for x in rows if x["set"] == s]
            ax.scatter([x[key] for x in pts], [x["asr_score"] for x in pts], s=46, color=col, edgecolor=SURF, linewidth=1.2, label=LAB[s])
        ax.set_xlabel(label)
        ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
        ax.set_title(f"{label}: Spearman ρ = {r[0]:.2f} (p = {r[1]:.3f})", color=INK, fontsize=11, loc="left")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("Clinical errors the ASR added (score per consult)")
    axes[1].legend(frameon=False, loc="upper left", fontsize=10)
    fig.suptitle(f"Real Whisper-medium transcripts, {len(rows)} consults: which metric tracks harm?", x=0.01, ha="left", color=INK, fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(path, dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    main()
