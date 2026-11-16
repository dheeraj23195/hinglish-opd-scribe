"""Build the clinician rating sheet (CSV) from simulated ASR errors.

    python scripts/make_rating_sheet.py --n 15 --out data/ratings/rating_items.csv

Each row is ONE isolated error, so a rater judges exactly one change.
The category column is hidden from raters in the blank sheet
(rating_sheet_blank.csv) to avoid anchoring.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opdscribe.metrics.calibrate import HARM_SCALE, make_items  # noqa: E402
from opdscribe.sim.asr_noise import SYSTEMS, corrupt_consult  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=15, help="items per clinical category")
    ap.add_argument("--out", default=str(ROOT / "data/ratings/rating_items.csv"))
    a = ap.parse_args()
    consults = [json.loads(x) for x in (ROOT / "data/synthetic/consults.jsonl").read_text(encoding="utf-8").splitlines()]
    uniform = SYSTEMS[2]
    items = make_items(consults, lambda c, k: corrupt_consult(c, uniform, seed=k), n_per_category=a.n)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    keys = ["item_id", "speaker", "said", "transcribed", "op", "ref_token", "hyp_token", "category", "consult_id", "turn"]
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows({k: it[k] for k in keys} for it in items)
    with open(out.with_name("rating_sheet_blank.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["item_id", "speaker", "what was said", "what the scribe wrote", "harm (0-4)", "comment"])
        for it in items:
            w.writerow([it["item_id"], it["speaker"], it["said"], it["transcribed"], "", ""])
    print(f"{len(items)} items -> {out}")
    print("scale:", json.dumps(HARM_SCALE, indent=1))


if __name__ == "__main__":
    main()
