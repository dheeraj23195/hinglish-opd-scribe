"""Run every mid-term experiment and write results/ (JSON, CSV, figures).

    python scripts/run_experiments.py            # full run (~10-15 min on 2 CPUs)
    python scripts/run_experiments.py --quick    # CI smoke run

E1  Extraction on clean transcripts (synthetic = sanity check, held-out = generalisation)
E2  Three simulated ASR systems: WER vs CS-WER vs concept-level clinical errors
E3  Random sweep of ASR error profiles: does WER / CS-WER track critical errors? (Spearman)
E4  Ablation: phonetic canonicalisation on vs off under spelling-variant noise
E5  Longitudinal memory: allergy-conflict detection with vs without visit history
E6  AMR stewardship flag (antibiotic for a viral diagnosis)
E7  FHIR: every bundle validates; share of concepts carrying a SNOMED code
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import statistics as st
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opdscribe import fhir  # noqa: E402
from opdscribe.extract import extract  # noqa: E402
from opdscribe.memory import PatientMemory  # noqa: E402
from opdscribe.metrics import clinical_error_score, compare_notes, cs_wer, wer  # noqa: E402
from opdscribe.normalize import tokenize  # noqa: E402
from opdscribe.pipeline import Scribe  # noqa: E402
from opdscribe.sim.asr_noise import SYSTEMS, corrupt_consult, random_profile  # noqa: E402
from opdscribe.sim.gold import gold_note, turns_of  # noqa: E402

OUT = ROOT / "results"
FIG = OUT / "figures"


def load(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def toks(c: dict) -> list[str]:
    return [t for tt in c["turns"] for t in tokenize(tt["text"])]


def score_against(ref_note, c_hyp, use_phonetic=True):
    return clinical_error_score(compare_notes(ref_note, extract(turns_of(c_hyp), use_phonetic=use_phonetic)))


def e1(syn, held, held2=()):
    out = {}
    for name, data in (("synthetic", syn), ("heldout", held), ("heldout_v2", held2)):
        if not data:
            continue
        tot = {"critical": 0, "major": 0, "minor": 0}
        kinds: dict[str, int] = {}
        n_facts = 0
        for c in data:
            g = gold_note(c)
            n_facts += len(g.findings) + len(g.medications) + len(g.allergies) + len(g.vitals)
            E = compare_notes(g, extract(turns_of(c)))
            for e in E:
                tot[e.severity] += 1
                kinds[e.kind] = kinds.get(e.kind, 0) + 1
        out[name] = {"n_consults": len(data), "n_gold_facts": n_facts, **tot, "error_kinds": kinds}
    return out


def e2(syn):
    rows = []
    for prof in SYSTEMS:
        W, C, S, K, any_crit = [], [], [], [], 0
        for i, c in enumerate(syn):
            h = corrupt_consult(c, prof, seed=i)
            W.append(wer(toks(c), toks(h)))
            C.append(cs_wer(toks(c), toks(h))["cs_wer"])
            s = score_against(gold_note(c), h)
            S.append(s["score"]); K.append(s["critical"]); any_crit += s["critical"] > 0
        rows.append({"system": prof.name, "wer": st.mean(W), "cs_wer": st.mean(C), "clinical_error_score": st.mean(S),
                     "critical_per_consult": st.mean(K), "pct_consults_with_critical": 100 * any_crit / len(syn)})
    return rows


def e3(syn, n_profiles, n_consults, seed=11):
    from scipy.stats import spearmanr

    rng = random.Random(seed)
    sub = rng.sample(syn, k=min(n_consults, len(syn)))
    pts = []
    for k in range(n_profiles):
        prof = random_profile(rng, k)
        W, C, K, S = [], [], [], []
        for i, c in enumerate(sub):
            h = corrupt_consult(c, prof, seed=1000 * k + i)
            W.append(wer(toks(c), toks(h))); C.append(cs_wer(toks(c), toks(h))["cs_wer"])
            s = score_against(gold_note(c), h); K.append(s["critical"]); S.append(s["score"])
        pts.append({"profile": prof.name, "wer": st.mean(W), "cs_wer": st.mean(C), "critical_per_consult": st.mean(K),
                    "clinical_error_score": st.mean(S), **{f"p_{a}": b for a, b in prof.p.items()}, "p_variant": prof.p_variant})
    rho_w = spearmanr([p["wer"] for p in pts], [p["critical_per_consult"] for p in pts])
    rho_c = spearmanr([p["cs_wer"] for p in pts], [p["critical_per_consult"] for p in pts])
    rho_ws = spearmanr([p["wer"] for p in pts], [p["clinical_error_score"] for p in pts])
    rho_cs = spearmanr([p["cs_wer"] for p in pts], [p["clinical_error_score"] for p in pts])
    return pts, {"n_profiles": n_profiles, "n_consults_each": len(sub),
                 "spearman_wer_vs_critical": [float(rho_w.statistic), float(rho_w.pvalue)],
                 "spearman_cswer_vs_critical": [float(rho_c.statistic), float(rho_c.pvalue)],
                 "spearman_wer_vs_score": [float(rho_ws.statistic), float(rho_ws.pvalue)],
                 "spearman_cswer_vs_score": [float(rho_cs.statistic), float(rho_cs.pvalue)]}


def e4(syn):
    out = {}
    for prof in (SYSTEMS[0], SYSTEMS[2]):
        res = {}
        for ph in (True, False):
            S, K = [], []
            for i, c in enumerate(syn):
                h = corrupt_consult(c, prof, seed=i)
                ref = extract(turns_of(c), use_phonetic=ph)
                s = clinical_error_score(compare_notes(gold_note(c), extract(turns_of(h), use_phonetic=ph)))
                S.append(s["score"]); K.append(s["critical"])
                _ = ref
            res["phonetic_on" if ph else "phonetic_off"] = {"clinical_error_score": st.mean(S), "critical_per_consult": st.mean(K)}
        out[prof.name] = res
    return out


def e5_e6_e7(syn):
    syn_sorted = sorted(syn, key=lambda c: (c["patient_id"], c["date"]))
    gold_by = {c["consult_id"]: set(c["gold"]["expected_flags"]) for c in syn}
    res = {}
    n_valid, n_bundles, coded, total_codes = 0, 0, 0, 0
    for use_mem in (True, False):
        scribe = Scribe(PatientMemory(), use_memory=use_mem)
        tp = fp = fn = 0
        amr_tp = amr_fp = amr_fn = 0
        mem_only = 0
        for c in syn_sorted:
            r = scribe.run(turns_of(c), c["patient_id"], c["consult_id"], c["date"])
            got = {f.kind for f in r.note.safety_flags}
            exp = gold_by[c["consult_id"]]
            a_got, a_exp = "allergy_conflict" in got, "allergy_conflict" in exp
            tp += a_got and a_exp; fp += a_got and not a_exp; fn += a_exp and not a_got
            if a_got and a_exp and not any(a.concept_id != "no_known_allergy" for a in r.note.allergies):
                mem_only += 1
            b_got, b_exp = "antibiotic_for_viral" in got, "antibiotic_for_viral" in exp
            amr_tp += b_got and b_exp; amr_fp += b_got and not b_exp; amr_fn += b_exp and not b_got
            if use_mem:
                n_bundles += 1
                try:
                    fhir.validate(r.fhir_bundle); n_valid += 1
                except Exception as ex:  # pragma: no cover
                    print("FHIR invalid", c["consult_id"], ex)
                for e in r.fhir_bundle["entry"]:
                    res_ = e["resource"]
                    cc = res_.get("code") or res_.get("medicationCodeableConcept")
                    if cc and res_["resourceType"] in ("Condition", "AllergyIntolerance", "MedicationRequest"):
                        total_codes += 1; coded += bool(cc.get("coding"))
        key = "with_memory" if use_mem else "without_memory"
        res[key] = {"allergy_conflict": {"expected": tp + fn, "detected": tp, "false_alarms": fp,
                                         "recall": tp / (tp + fn) if tp + fn else None, "caught_only_via_history": mem_only},
                    "antibiotic_for_viral": {"expected": amr_tp + amr_fn, "detected": amr_tp, "false_alarms": amr_fp}}
    res["fhir"] = {"bundles": n_bundles, "valid": n_valid, "coded_share": coded / total_codes if total_codes else None,
                   "coded": coded, "codeable_resources": total_codes}
    return res


def figures(sys_rows, pts, rho):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker  # noqa: F401

    INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    COLS = ["#2a78d6", "#eb6834", "#1baf7a"]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                         "xtick.color": INK2, "ytick.color": INK2, "figure.facecolor": SURF, "axes.facecolor": SURF})
    names = ["A: spelling-noisy", "B: clinically brittle", "C: uniform"]
    short = ["A\nspelling-noisy", "B\nclinically brittle", "C\nuniform"]
    metrics = [("wer", "Word error rate", "{:.0%}"), ("cs_wer", "Clinical-severity WER", "{:.0%}"),
               ("critical_per_consult", "Critical clinical errors\nper consult", "{:.2f}")]
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2))
    for ax, (key, title, fmt) in zip(axes, metrics):
        vals = [next(r[key] for r in sys_rows if r["system"] == n) for n in names]
        bars = ax.bar(range(3), vals, color=COLS, width=0.62, edgecolor=SURF, linewidth=2)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v, fmt.format(v), ha="center", va="bottom", color=INK, fontsize=11, fontweight="bold")
        ax.set_xticks(range(3), short, fontsize=9.5)
        ax.set_title(title, color=INK, fontsize=12, loc="left")
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.yaxis.grid(True, color=GRID, linewidth=0.8); ax.set_axisbelow(True)
        ax.set_yticklabels([])
        ax.tick_params(axis="y", length=0)
        ax.set_ylim(0, max(vals) * 1.22)
    fig.suptitle("Lowest WER ≠ safest: system B has the best WER and the most critical errors", x=0.01, ha="left", color=INK, fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(FIG / "fig1_systems.png", dpi=200)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True)
    y = [p["clinical_error_score"] for p in pts]
    for ax, key, label, r_s, r_c in ((axes[0], "wer", "Word error rate", rho["spearman_wer_vs_score"][0], rho["spearman_wer_vs_critical"][0]),
                                     (axes[1], "cs_wer", "Clinical-severity WER", rho["spearman_cswer_vs_score"][0], rho["spearman_cswer_vs_critical"][0])):
        ax.scatter([p[key] for p in pts], y, s=34, color=COLS[0], edgecolor=SURF, linewidth=1, alpha=0.9)
        ax.set_xlabel(label)
        ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
        ax.set_title(f"{label}\nρ = {r_s:.2f} vs clinical error score  ·  ρ = {r_c:.2f} vs critical errors only",
                     color=INK, fontsize=10.5, loc="left")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(True, color=GRID, linewidth=0.8); ax.set_axisbelow(True)
    axes[0].set_ylabel("Clinical error score per consult")
    fig.suptitle(f"{len(pts)} random ASR error profiles: which metric tracks clinical harm? (Spearman ρ)", x=0.01, ha="left", color=INK, fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(FIG / "fig2_sweep.png", dpi=200)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True); FIG.mkdir(exist_ok=True)
    syn = load(ROOT / "data/synthetic/consults.jsonl")
    held = load(ROOT / "data/heldout/heldout.jsonl")
    held2 = load(ROOT / "data/heldout/heldout_v2.jsonl")
    if a.quick:
        syn = syn[:15]
    t0 = time.time()
    results = {"E1_extraction": e1(syn, held, held2)}; print("E1", round(time.time() - t0), "s", flush=True)
    sys_rows = e2(syn); results["E2_systems"] = sys_rows; print("E2", round(time.time() - t0), "s", flush=True)
    pts, rho = e3(syn, 8 if a.quick else 80, 10 if a.quick else 30); results["E3_sweep"] = rho
    print("E3", round(time.time() - t0), "s", flush=True)
    results["E4_ablation"] = e4(syn); print("E4", round(time.time() - t0), "s", flush=True)
    results.update({"E5_E6_E7": e5_e6_e7(syn)})
    (OUT / "results.json").write_text(json.dumps(results, indent=2))
    with open(OUT / "e3_sweep.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(pts[0])); w.writeheader(); w.writerows(pts)
    figures(sys_rows, pts, rho)
    print(json.dumps(results, indent=2))
    print("done in", round(time.time() - t0), "s")


if __name__ == "__main__":
    main()
