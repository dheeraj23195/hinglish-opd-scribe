"""ASR backends. Every backend exposes `transcribe(path) -> list[Turn]`.

* `TranscriptFileASR` – reads a JSON transcript (used for evaluation and demos)
* `FasterWhisperASR`  – open-source Whisper via faster-whisper (local, CPU/GPU)
* `AWSTranscribeASR`  – Amazon Transcribe in ap-south-1 (Mumbai) so audio stays in India

The Whisper and AWS backends are written against the public APIs but have
NOT yet been run on consult audio in this repo (no model download / AWS
credentials in the build environment). They are phase-2 work.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..schema import Turn


class TranscriptFileASR:
    """Reads {"turns": [{"speaker": ..., "text": ...}]} JSON."""

    def transcribe(self, path: str) -> list[Turn]:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return [Turn(t["speaker"], t["text"], t.get("start"), t.get("end")) for t in data["turns"]]


class FasterWhisperASR:
    """Whisper with language='hi'. Whisper emits Hindi in Devanagari; the
    pipeline's romaniser maps it onto the Hinglish lexicon. Speaker labels
    need a separate diariser (e.g. pyannote); without one, segments
    alternate speakers on long pauses as a crude fallback."""

    def __init__(self, model_size: str = "small", device: str = "cpu", pause_s: float = 1.2) -> None:
        from faster_whisper import WhisperModel  # optional dependency

        self.model = WhisperModel(model_size, device=device, compute_type="int8")
        self.pause_s = pause_s

    def transcribe(self, path: str) -> list[Turn]:
        segments, _ = self.model.transcribe(path, language="hi", vad_filter=True)
        turns: list[Turn] = []
        spk, last_end = 0, 0.0
        for s in segments:
            if turns and s.start - last_end > self.pause_s:
                spk = 1 - spk
            turns.append(Turn(f"spk_{spk}", s.text.strip(), s.start, s.end))
            last_end = s.end
        return turns


class AWSTranscribeASR:
    """Amazon Transcribe batch job with speaker diarisation, hi-IN.
    Requires an S3 bucket in ap-south-1 and IAM credentials."""

    def __init__(self, bucket: str, region: str = "ap-south-1", language: str = "hi-IN", max_speakers: int = 3) -> None:
        import boto3  # optional dependency

        self.s3 = boto3.client("s3", region_name=region)
        self.tx = boto3.client("transcribe", region_name=region)
        self.bucket, self.language, self.max_speakers = bucket, language, max_speakers

    def transcribe(self, path: str) -> list[Turn]:
        import time
        import urllib.request
        import uuid

        key = f"opdscribe/{uuid.uuid4()}{Path(path).suffix}"
        self.s3.upload_file(path, self.bucket, key)
        job = f"opdscribe-{uuid.uuid4().hex[:12]}"
        self.tx.start_transcription_job(
            TranscriptionJobName=job, LanguageCode=self.language, Media={"MediaFileUri": f"s3://{self.bucket}/{key}"},
            Settings={"ShowSpeakerLabels": True, "MaxSpeakerLabels": self.max_speakers},
        )
        while True:
            st = self.tx.get_transcription_job(TranscriptionJobName=job)["TranscriptionJob"]
            if st["TranscriptionJobStatus"] in ("COMPLETED", "FAILED"):
                break
            time.sleep(5)
        if st["TranscriptionJobStatus"] == "FAILED":
            raise RuntimeError(st.get("FailureReason"))
        with urllib.request.urlopen(st["Transcript"]["TranscriptFileUri"]) as fh:
            res = json.load(fh)
        turns: list[Turn] = []
        for seg in res["results"].get("audio_segments", []):
            turns.append(Turn(seg.get("speaker_label", "spk_0"), seg["transcript"], float(seg["start_time"]), float(seg["end_time"])))
        self.s3.delete_object(Bucket=self.bucket, Key=key)  # do not retain audio
        return turns
