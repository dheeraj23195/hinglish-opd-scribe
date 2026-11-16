"""Write tts_jobs.tsv (turn id, speaker, mixed-script text) for make_audio.command.

    python scripts/tts/make_tts_jobs.py > tts_jobs.tsv
Then on a Mac: put tts_jobs.tsv next to make_audio.command and double-click it.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from opdscribe.sim.to_devanagari import to_mixed_script  # noqa: E402

for f in ("data/synthetic/consults.jsonl", "data/heldout/heldout.jsonl", "data/heldout/heldout_v2.jsonl"):
    for line in (ROOT / f).read_text(encoding="utf-8").splitlines():
        c = json.loads(line)
        for i, t in enumerate(c["turns"]):
            print(f'{c["consult_id"]}_{i:02d}\t{t["speaker"]}\t{to_mixed_script(t["text"]).replace(chr(9), " ")}')
