"""Azure Speech: fast transcription (STT, any length) and pronunciation assessment (scripted,
via the Speech SDK so takes longer than 60 s work)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from ..config import get_settings
from .base import EngineError, Transcript, TWord


def _region_key() -> tuple[str, str]:
    s = get_settings()
    if not s.azure_speech_key or not s.azure_speech_region:
        raise EngineError("EHNGLISH_AZURE_SPEECH_KEY / _REGION not set")
    return s.azure_speech_region, s.azure_speech_key


# ---------------------------------------------------------------- STT (fast transcription)
def transcribe(path: Path, *, language: str = "en", timeout: float = 180) -> Transcript:
    region, key = _region_key()
    locale = {"en": "en-US", "ko": "ko-KR"}.get(language, language)
    url = f"https://{region}.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe?api-version=2024-11-15"
    definition = {"locales": [locale], "profanityFilterMode": "None"}
    with path.open("rb") as f:
        r = httpx.post(
            url,
            headers={"Ocp-Apim-Subscription-Key": key},
            files={
                "audio": (path.name, f, "audio/wav"),
                "definition": (None, json.dumps(definition), "application/json"),
            },
            timeout=timeout,
        )
    if r.status_code != 200:
        raise EngineError(f"azure stt {r.status_code}: {r.text[:300]}")
    return parse_stt(r.json(), language)


def parse_stt(data: dict, language: str = "en") -> Transcript:
    words: list[TWord] = []
    for ph in data.get("phrases", []):
        conf = ph.get("confidence")
        for w in ph.get("words", []):
            start = w.get("offsetMilliseconds")
            dur = w.get("durationMilliseconds")
            words.append(
                TWord(
                    w.get("text", ""),
                    start / 1000 if start is not None else None,
                    (start + dur) / 1000 if start is not None and dur is not None else None,
                    conf,
                )
            )
    text = " ".join(p.get("text", "") for p in data.get("combinedPhrases", [])).strip()
    return Transcript("azure", text, words, language, None, data)


# ---------------------------------------------------------------- pronunciation assessment
@dataclass
class PronWord:
    word: str
    accuracy: float | None
    error_type: (
        str | None
    )  # None | Omission | Insertion | Mispronunciation | UnexpectedBreak | MissingBreak
    phonemes: list[dict] = field(default_factory=list)  # {phoneme, accuracy}
    start: float | None = None
    end: float | None = None


@dataclass
class PronResult:
    accuracy: float | None
    fluency: float | None
    completeness: float | None
    prosody: float | None
    pron_score: float | None
    words: list[PronWord]
    raw: list[dict]

    def to_dict(self) -> dict:
        return {
            "accuracy": self.accuracy,
            "fluency": self.fluency,
            "completeness": self.completeness,
            "prosody": self.prosody,
            "pron_score": self.pron_score,
            "words": [
                {
                    "word": w.word,
                    "accuracy": w.accuracy,
                    "error_type": w.error_type,
                    "phonemes": w.phonemes,
                    "start": w.start,
                    "end": w.end,
                }
                for w in self.words
            ],
            "raw": self.raw,
        }


def pronunciation_assessment(
    path: Path, reference_text: str, *, language: str = "en-US"
) -> PronResult:
    """Scripted mode, phoneme granularity, IPA, prosody on. Uses continuous recognition so long
    read-alouds are scored in full; per-segment JSON results are merged."""
    import azure.cognitiveservices.speech as speechsdk  # heavy import, keep local

    region, key = _region_key()
    cfg = speechsdk.SpeechConfig(subscription=key, region=region)
    cfg.speech_recognition_language = language
    audio = speechsdk.audio.AudioConfig(filename=str(path))
    pa = speechsdk.PronunciationAssessmentConfig(
        reference_text=reference_text,
        grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
        granularity=speechsdk.PronunciationAssessmentGranularity.Phoneme,
        enable_miscue=True,
    )
    pa.phoneme_alphabet = "IPA"
    pa.enable_prosody_assessment()
    rec = speechsdk.SpeechRecognizer(speech_config=cfg, audio_config=audio)
    pa.apply_to(rec)
    results: list[dict] = []
    done = False

    def on_result(evt: speechsdk.SpeechRecognitionEventArgs) -> None:
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            j = evt.result.properties.get(speechsdk.PropertyId.SpeechServiceResponse_JsonResult)
            if j:
                results.append(json.loads(j))

    def on_stop(_evt: object) -> None:
        nonlocal done
        done = True

    rec.recognized.connect(on_result)
    rec.session_stopped.connect(on_stop)
    rec.canceled.connect(on_stop)
    rec.start_continuous_recognition()
    import time

    t0 = time.time()
    while not done and time.time() - t0 < 600:
        time.sleep(0.2)
    rec.stop_continuous_recognition()
    return merge_pron_results(results)


def merge_pron_results(segments: list[dict]) -> PronResult:
    """Merge per-utterance Azure JSON into one result. Segment scores are weighted by word count."""
    words: list[PronWord] = []
    acc = flu = comp = pros = score = 0.0
    weight = 0
    for seg in segments:
        nb = (seg.get("NBest") or [{}])[0]
        pa = nb.get("PronunciationAssessment", {})
        segwords = nb.get("Words", [])
        n = max(1, len(segwords))
        weight += n
        acc += n * pa.get("AccuracyScore", 0)
        flu += n * pa.get("FluencyScore", 0)
        comp += n * pa.get("CompletenessScore", 0)
        pros += n * pa.get("ProsodyScore", 0)
        score += n * pa.get("PronScore", 0)
        for w in segwords:
            wpa = w.get("PronunciationAssessment", {})
            off = w.get("Offset")
            dur = w.get("Duration")
            words.append(
                PronWord(
                    w.get("Word", ""),
                    wpa.get("AccuracyScore"),
                    wpa.get("ErrorType") if wpa.get("ErrorType") not in (None, "None") else None,
                    [
                        {
                            "phoneme": p.get("Phoneme"),
                            "accuracy": p.get("PronunciationAssessment", {}).get("AccuracyScore"),
                        }
                        for p in w.get("Phonemes", [])
                    ],
                    off / 1e7 if off is not None else None,
                    (off + dur) / 1e7 if off is not None and dur is not None else None,
                )
            )
    if weight == 0:
        return PronResult(None, None, None, None, None, [], segments)
    r = lambda v: round(v / weight, 2)  # noqa: E731
    return PronResult(r(acc), r(flu), r(comp), r(pros), r(score), words, segments)
