#!/usr/bin/env python3
"""Draft an R3 sermon-clip task from a church-app video (plan §4.3 R3, §4.5, §10 item 2).

Steps: fetch the audio with yt-dlp → transcribe a span with Deepgram to find the densest two
minutes of speech → cut that window to a fixed 16 kHz WAV under content/audio/<form>/ →
transcribe the clip exactly → ask Claude for four multiple-choice questions (structured, keyed)
→ print a YAML task block (comprehension task with the clip as stimulus, plus a retell item) to
paste into the form. The clip transcript goes into target.transcript so the retell can be scored
for idea-unit coverage. Nothing is written into the form automatically; the native-speaker editor
reviews the questions first.

Usage (from server/, with keys in the environment):
  uv run python ../content/draft_sermon_task.py --video fse5pcDpXto --form rotating-R3-A \
      [--search-start 20:00 --search-len 8:00 --clip-len 120]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "server"))
from app.engines import deepgram  # noqa: E402
from app.engines.claude import structured  # noqa: E402

QUESTION_SYSTEM = (
    "You write listening-comprehension items for an adult English learner (Korean L1, B1–B2) who "
    "has just heard a two-minute excerpt of a church sermon once. Write four multiple-choice "
    "questions that can be answered only from what was said in the excerpt: main point, a "
    "specific detail, a reason or consequence, and the meaning of a phrase as used. Four options "
    "each, one correct, distractors plausible, all options about the same length. Plain wording. "
    "Return the correct option as index 0; the app shuffles options."
)


def hms(s: str) -> float:
    parts = [float(p) for p in s.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--form", default="rotating-R3-A")
    ap.add_argument("--search-start", default="20:00")
    ap.add_argument("--search-len", default="8:00")
    ap.add_argument("--clip-len", type=float, default=120.0)
    args = ap.parse_args()
    if not shutil.which("yt-dlp") or not shutil.which("ffmpeg"):
        sys.exit("yt-dlp and ffmpeg are required")
    out_dir = ROOT / "audio" / args.form
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = tmp / "audio.m4a"
        run(["yt-dlp", "-q", "--no-update", "--js-runtimes", "node", "-f", "bestaudio[ext=m4a]/bestaudio", "-o", str(src), f"https://www.youtube.com/watch?v={args.video}"])
        s0, ln = hms(args.search_start), hms(args.search_len)
        span = tmp / "span.wav"
        run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(s0), "-t", str(ln), "-i", str(src), "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", str(span)])
        print(f"transcribing search span {args.search_start} + {args.search_len} …")
        tr = deepgram.transcribe(span)
        words = [w for w in tr.words if w.start is not None]
        if len(words) < 50:
            sys.exit("too little speech in the search span; try another --search-start")
        # densest window of clip_len seconds (most words), scanning word starts
        best_start, best_n = 0.0, 0
        starts = [w.start for w in words]
        for i, st in enumerate(starts):
            n = sum(1 for x in starts[i:] if x < st + args.clip_len)
            if n > best_n:
                best_start, best_n = st, n
        # snap to a pause before the first word if possible
        clip_start = max(0.0, best_start - 0.3)
        abs_start = s0 + clip_start
        out = out_dir / f"sermon-{args.video}-{int(abs_start)}.wav"
        run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(clip_start), "-t", str(args.clip_len), "-i", str(span), "-acodec", "pcm_s16le", str(out)])
        print(f"clip: {out} (starts at {int(abs_start) // 60}:{int(abs_start) % 60:02d} in the video, {best_n} words)")
        clip_tr = deepgram.transcribe(out)
        transcript = clip_tr.text.strip()
    schema = {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}, "minItems": 4, "maxItems": 4}, "kind": {"type": "string"}},
                    "required": ["text", "options", "kind"],
                },
                "minItems": 4,
                "maxItems": 4,
            }
        },
        "required": ["questions"],
    }
    r = structured(QUESTION_SYSTEM, f"Excerpt transcript:\n{transcript}", schema, tool_name="questions")
    rel = f"audio/{args.form}/{out.name}"
    yaml_text = f'''  - id: R3-sermon
    type: multiple_choice
    title: {{ en: "Sermon clip", ko: "설교 발췌" }}
    instructions:
      en: "You will hear two minutes of a sermon from your church, once. Then answer the questions from memory."
      ko: "교회 설교 두 분 분량을 한 번 듣게 됩니다. 그다음 기억을 바탕으로 문제에 답하세요."
    timing: {{ prep_s: 0, respond_s: 40 }}
    audio: {rel}
    target:
      genre: sermon
      source: {{ video: {args.video}, start_s: {int(abs_start)}, clip_s: {int(args.clip_len)} }}
      transcript: {transcript!r}
    items:
'''
    for i, q in enumerate(r["questions"], 1):
        opts = ", ".join(f'"{o.replace(chr(34), chr(39))}"' for o in q["options"])
        yaml_text += f'      - {{ id: R3-sermon-q{i}, text: "{q["text"].replace(chr(34), chr(39))}", options: [{opts}], target: {{ answer: 0, kind: {q.get("kind", "detail")} }} }}\n'
    yaml_text += '''  - id: R3-sermon-retell
    type: describe_opinion
    title: { en: "Retell the sermon excerpt", ko: "설교 발췌 다시 말하기" }
    instructions:
      en: "In your own words, say everything you remember from the sermon excerpt. Sixty seconds."
      ko: "설교 발췌에서 기억나는 모든 내용을 자신의 말로 말하세요. 60초입니다."
    timing: { prep_s: 5, respond_s: 60, max_s: 65 }
    allow_rerecord: false
    items:
      - id: R3-sermon-retell-1
        prompt: { en: "Retell the sermon excerpt.", ko: "설교 발췌를 다시 말하세요." }
        target: { stage: retell, genre: sermon }
'''
    print("\n--- paste into the form (before R3-axb) ---\n" + yaml_text)
    (out_dir / f"{out.stem}.task.yaml").write_text(yaml_text, encoding="utf-8")
    print(f"also saved to {out_dir / (out.stem + '.task.yaml')}")


if __name__ == "__main__":
    main()
