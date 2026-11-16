"""Real-ASR benchmark: synthesised (or recorded) consult audio -> Whisper ->
scribe -> WER vs CS-WER vs concept-level clinical errors.

    python scripts/asr_benchmark.py --audio-dir AUDIO --model MODEL_DIR [--model MODEL2] \
        --snr clean 20 10 5 --consults data/heldout/heldout.jsonl data/synthetic/consults.jsonl --limit 40

Audio files are named <consult_id>_<turn:02d>.(m4a|aiff|wav) (oracle segmentation:
one file per speaker turn, so diarisation errors are excluded and reported separately).

Noise: "OPD babble" = 4 other speakers' clips mixed at random offsets plus
low-level broadband noise, added at the requested speech-to-noise ratio.
Transcripts are cached in results/asr/cache_<model>_<snr>.jsonl so runs resume.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opdscribe.extract import extract  # noqa: E402
from opdscribe.metrics import clinical_error_score, compare_notes, cs_wer, wer  # noqa: E402
from opdscribe.normalize import normalize_text  # noqa: E402
from opdscribe.schema import Turn  # noqa: E402
from opdscribe.sim.gold import gold_note  # noqa: E402

SR = 16000
OUT = ROOT / "results" / "asr"


def load_audio(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "quiet", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def find_clip(audio_dir: Path, turn_id: str) -> Path | None:
    for ext in (".m4a", ".aiff", ".wav", ".mp3"):
        p = audio_dir / f"{turn_id}{ext}"
        if p.exists():
            return p
    return None


def add_babble(x: np.ndarray, others: list[np.ndarray], snr_db: float, rng: np.random.Generator) -> np.ndarray:
    noise = np.zeros_like(x)
    for o in others:
        if len(o) == 0:
            continue
        o = np.tile(o, int(np.ceil(len(x) / len(o))) + 1)
        start = rng.integers(0, len(o) - len(x))
        seg = o[start:start + len(x)]
        noise += seg / (np.sqrt(np.mean(seg ** 2)) + 1e-9)
    noise += 0.3 * rng.standard_normal(len(x))  # fans, traffic
    ps = np.mean(x ** 2) + 1e-12
    pn = np.mean(noise ** 2) + 1e-12
    y = x + noise * np.sqrt(ps / (pn * 10 ** (snr_db / 10)))
    return (y / max(1.0, np.max(np.abs(y)))).astype(np.float32)


def transcribe_all(model_dir: str, consults: list[dict], audio_dir: Path, snr: str, beam: int) -> dict[str, str]:
    from faster_whisper import WhisperModel

    name = Path(model_dir).name
    cache_p = OUT / f"cache_{name}_{snr}.jsonl"
    cache = {}
    if cache_p.exists():
        for line in cache_p.read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            cache[d["id"]] = d["text"]
    model = WhisperModel(model_dir, device="cpu", compute_type="int8")
    rng = np.random.default_rng(1234)
    all_ids = [f"{c['consult_id']}_{i:02d}" for c in consults for i in range(len(c["turns"]))]
    pool = [p for p in (find_clip(audio_dir, t) for t in all_ids[::7]) if p][:60]
    pool_audio = [load_audio(p) for p in pool] if snr != "clean" else []
    t0, n_new, audio_s = time.time(), 0, 0.0
    with open(cache_p, "a", encoding="utf-8") as fh:
        for c in consults:
            for i, _ in enumerate(c["turns"]):
                tid = f"{c['consult_id']}_{i:02d}"
                if tid in cache:
                    continue
                p = find_clip(audio_dir, tid)
                if p is None:
                    continue
                x = load_audio(p)
                audio_s += len(x) / SR
                if snr != "clean":
                    others = [pool_audio[k] for k in rng.choice(len(pool_audio), size=4, replace=len(pool_audio) < 4)]
                    x = add_babble(x, others, float(snr), rng)
                segs, _ = model.transcribe(x, language="hi", beam_size=beam, condition_on_previous_text=False,
                                           vad_filter=False, compression_ratio_threshold=2.4)
                text = " ".join(s.text.strip() for s in segs).strip()
                cache[tid] = text
                fh.write(json.dumps({"id": tid, "text": text}, ensure_ascii=False) + "\n")
                fh.flush()
                n_new += 1
    if n_new:
        dt = time.time() - t0
        print(f"  {name}/{snr}: {n_new} clips, {audio_s/60:.1f} min audio in {dt/60:.1f} min (RTF {dt/max(audio_s,1):.2f})", flush=True)
    return cache


def evaluate(consults: list[dict], hyp: dict[str, str]) -> dict:
    rows = []
    for c in consults:
        ids = [f"{c['consult_id']}_{i:02d}" for i in range(len(c["turns"]))]
        if not all(t in hyp for t in ids):
            continue
        ref_tok = [t for tt in c["turns"] for t in normalize_text(tt["text"])]
        hyp_tok = [t for t in ids for t in normalize_text(hyp[t])]
        turns = [Turn(tt["speaker"], hyp[t]) for tt, t in zip(c["turns"], ids)]
        E = compare_notes(gold_note(c), extract(turns))
        s = clinical_error_score(E)
        rows.append({"consult_id": c["consult_id"], "wer": wer(ref_tok, hyp_tok), "cs_wer": cs_wer(ref_tok, hyp_tok)["cs_wer"],
                     **s, "errors": [(e.severity, e.kind, e.detail) for e in E]})
    if not rows:
        return {"n": 0}
    m = lambda k: float(np.mean([r[k] for r in rows]))  # noqa: E731
    return {"n": len(rows), "wer": m("wer"), "cs_wer": m("cs_wer"), "clinical_error_score": m("score"),
            "critical_per_consult": m("critical"), "major_per_consult": m("major"),
            "pct_consults_with_critical": 100 * float(np.mean([r["critical"] > 0 for r in rows])), "per_consult": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio-dir", required=True)
    ap.add_argument("--model", action="append", required=True)
    ap.add_argument("--snr", nargs="+", default=["clean", "20", "10", "5"])
    ap.add_argument("--consults", nargs="+", default=[str(ROOT / "data/heldout/heldout.jsonl"), str(ROOT / "data/synthetic/consults.jsonl")])
    ap.add_argument("--limit", type=int, default=40, help="max consults (held-out first)")
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--tag", default="", help="suffix for result files (e.g. heldout_v2)")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    consults = [json.loads(x) for f in a.consults for x in Path(f).read_text(encoding="utf-8").splitlines() if x.strip()]
    consults = consults[: a.limit]
    summary = {}
    for model_dir in a.model:
        for snr in a.snr:
            hyp = transcribe_all(model_dir, consults, Path(a.audio_dir), snr, a.beam)
            res = evaluate(consults, hyp)
            key = f"{Path(model_dir).name}|{snr}" + (f"|{a.tag}" if a.tag else "")
            summary[key] = {k: v for k, v in res.items() if k != "per_consult"}
            (OUT / f"eval_{Path(model_dir).name}_{snr}{'_' + a.tag if a.tag else ''}.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
            print(key, json.dumps(summary[key]), flush=True)
    sp = OUT / "summary.json"
    old = json.loads(sp.read_text()) if sp.exists() else {}
    old.update(summary)
    sp.write_text(json.dumps(old, indent=2))


if __name__ == "__main__":
    main()
