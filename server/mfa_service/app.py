"""Tiny HTTP shim around the Montreal Forced Aligner CLI. Runs inside the official MFA image
(deploy/docker-compose.yml service `mfa`). POST /align with a WAV and its transcript; returns word
and phone intervals as JSON. One alignment at a time; the worker is the only client.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ACOUSTIC = os.environ.get("MFA_ACOUSTIC", "english_us_arpa")
DICT = os.environ.get("MFA_DICTIONARY", "english_us_arpa")
PORT = int(os.environ.get("PORT", "8700"))


def parse_textgrid(path: Path) -> dict:
    """Minimal TextGrid parser for MFA output (tiers: words, phones)."""
    text = path.read_text(encoding="utf-8")
    tiers: dict[str, list[dict]] = {}
    cur: str | None = None
    for m in re.finditer(
        r'name = "([^"]*)"|xmin = ([\d.]+)\s+xmax = ([\d.]+)\s+text = "([^"]*)"', text
    ):
        if m.group(1) is not None:
            cur = m.group(1)
            tiers[cur] = []
        elif cur:
            tiers[cur].append(
                {"start": float(m.group(2)), "end": float(m.group(3)), "text": m.group(4)}
            )
    words = [
        {"word": i["text"], "start": i["start"], "end": i["end"]}
        for i in tiers.get("words", [])
        if i["text"]
    ]
    phones = [
        {"phone": i["text"], "start": i["start"], "end": i["end"]} for i in tiers.get("phones", [])
    ]
    return {"words": words, "phones": phones}


def run_align(wav: bytes, transcript: str) -> dict:
    work = Path(tempfile.mkdtemp(prefix="mfa-"))
    try:
        corpus = work / "corpus"
        out = work / "out"
        corpus.mkdir()
        (corpus / "take.wav").write_bytes(wav)
        (corpus / "take.txt").write_text(transcript, encoding="utf-8")
        cmd = [
            "mfa",
            "align",
            "--clean",
            "--single_speaker",
            "--output_format",
            "long_textgrid",
            "--beam",
            "100",
            "--retry_beam",
            "400",
            str(corpus),
            DICT,
            ACOUSTIC,
            str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        tg = out / "take.TextGrid"
        if proc.returncode != 0 or not tg.exists():
            return {
                "error": (proc.stderr or proc.stdout)[-2000:],
                "unaligned": True,
                "words": [],
                "phones": [],
            }
        res = parse_textgrid(tg)
        res["unaligned"] = False
        return res
    finally:
        shutil.rmtree(work, ignore_errors=True)


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self._json(200, {"ok": True, "acoustic": ACOUSTIC, "dictionary": DICT})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/align":
            return self._json(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", "0"))
        ctype = self.headers.get("Content-Type", "")
        body = self.rfile.read(length)
        m = re.search(r"boundary=([^;]+)", ctype)
        if not m:
            return self._json(400, {"error": "multipart expected"})
        boundary = m.group(1).strip('"').encode()
        wav = None
        text = None
        for part in body.split(b"--" + boundary):
            if b"\r\n\r\n" not in part:
                continue
            head, _, data = part.partition(b"\r\n\r\n")
            data = data.rstrip(b"\r\n").removesuffix(b"--")
            if b'name="audio"' in head:
                wav = data
            elif b'name="text"' in head:
                text = data.decode("utf-8")
        if wav is None or text is None:
            return self._json(400, {"error": "audio and text required"})
        self._json(200, run_align(wav, text))

    def log_message(self, fmt: str, *args: object) -> None:  # quieter
        pass


if __name__ == "__main__":
    print(f"mfa shim on :{PORT} ({ACOUSTIC}, {DICT})", flush=True)
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
