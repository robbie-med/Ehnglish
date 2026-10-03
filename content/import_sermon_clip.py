#!/usr/bin/env python3
"""Import a sermon clip from the family's church app (SermonFetch) for an R3 listening task
(plan §4.3 R3, §4.5). Answers §10 item 2: the app stores YouTube video ids and transcripts in
`sermons.db`; audio is fetched with yt-dlp and cut with ffmpeg.

Usage (from server/):
  uv run python ../content/import_sermon_clip.py --video <youtube id> --start 12:40 --end 14:50 \
      --form rotating-R3-A --task R3-sermon
Writes content/audio/<form>/sermon-<video>-<start>.wav (16 kHz mono) and prints the transcript
excerpt (if SermonFetch has one) so the questions can be written into the form by hand. The task
itself is added to the form YAML by the author; this script never edits forms.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERMONFETCH_DB = Path("/home/user/Projects/SermonFetch/sermons.db")


def hms(s: str) -> float:
    parts = [float(p) for p in s.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, sec = parts
    return h * 3600 + m * 60 + sec


def transcript_excerpt(video_id: str, start: float, end: float) -> str | None:
    if not SERMONFETCH_DB.exists():
        return None
    con = sqlite3.connect(f"file:{SERMONFETCH_DB}?mode=ro", uri=True)
    try:
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        # SermonFetch keeps a transcript FTS table; column names vary by version, so probe gently.
        for t in sorted(tables):
            if "transcript" not in t:
                continue
            cols = [c[1] for c in con.execute(f"pragma table_info({t})")]
            if "video_id" in cols and "text" in cols:
                rows = con.execute(f"select text from {t} where video_id=?", (video_id,)).fetchall()
                if rows:
                    return rows[0][0][:4000]
    finally:
        con.close()
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--form", default="rotating-R3-A")
    args = ap.parse_args()
    if not shutil.which("yt-dlp") or not shutil.which("ffmpeg"):
        sys.exit("yt-dlp and ffmpeg are required (pipx install yt-dlp)")
    start, end = hms(args.start), hms(args.end)
    out_dir = ROOT / "audio" / args.form
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"sermon-{args.video}-{int(start)}.wav"
    tmp = out_dir / f".{args.video}.m4a"
    subprocess.run(["yt-dlp", "-f", "bestaudio[ext=m4a]/bestaudio", "-o", str(tmp), f"https://www.youtube.com/watch?v={args.video}"], check=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(start), "-to", str(end), "-i", str(tmp),
         "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", str(out)],
        check=True,
    )
    tmp.unlink(missing_ok=True)
    print(f"wrote {out} ({end - start:.0f} s)")
    ex = transcript_excerpt(args.video, start, end)
    print("\n--- transcript (whole video, from SermonFetch) ---\n" + ex if ex else "\n(no transcript in SermonFetch for this video; use the voted transcript after a test run)")
    print(f"\nAdd to {args.form}.yaml a multiple_choice task with `audio: audio/{args.form}/{out.name}` and target.genre: sermon, plus a retell item.")


if __name__ == "__main__":
    main()
