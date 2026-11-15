"""Command line: `opdscribe run transcript.json --patient P001 --date 2026-08-01`."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .asr import TranscriptFileASR
from .memory import PatientMemory
from .pipeline import Scribe


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="opdscribe")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="scribe one consult")
    r.add_argument("input", help="transcript JSON (or audio with --asr whisper|aws)")
    r.add_argument("--patient", required=True)
    r.add_argument("--encounter", default=None)
    r.add_argument("--date", required=True)
    r.add_argument("--memory", default="opdscribe_memory.sqlite", help="SQLite file for visit history")
    r.add_argument("--asr", choices=["file", "whisper", "aws"], default="file")
    r.add_argument("--aws-bucket", default=None)
    r.add_argument("--out", default="out")
    a = ap.parse_args(argv)

    if a.asr == "file":
        asr = TranscriptFileASR()
    elif a.asr == "whisper":
        from .asr import FasterWhisperASR
        asr = FasterWhisperASR()
    else:
        from .asr import AWSTranscribeASR
        asr = AWSTranscribeASR(a.aws_bucket)

    scribe = Scribe(PatientMemory(a.memory), asr=asr)
    enc = a.encounter or f"{a.patient}-{a.date}"
    res = scribe.run_audio(a.input, a.patient, enc, a.date)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{enc}.fhir.json").write_text(json.dumps(res.fhir_bundle, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / f"{enc}.md").write_text(res.markdown, encoding="utf-8")
    print(res.markdown)
    print(f"wrote {out / (enc + '.fhir.json')} and {out / (enc + '.md')}")


if __name__ == "__main__":
    main()
