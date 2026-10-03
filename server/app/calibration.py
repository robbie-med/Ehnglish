"""External calibration file (plan §5.5, §7): content/calibration.yaml holds official TOEFL/IELTS
scores once she has them; the dashboard refits its CEFR estimates to them.

Example:
    external:
      - date: 2027-03-15
        test: toefl          # or ielts
        speaking: 22
        listening: 19
        reading: 24
        writing: 21
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml


@lru_cache
def _load(path: str, mtime: float) -> dict:
    p = Path(path)
    if not p.exists():
        return {"external": []}
    with p.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("external", [])
    return data


def load_calibration(content_dir: Path | str) -> dict:
    p = Path(content_dir) / "calibration.yaml"
    return _load(str(p), p.stat().st_mtime if p.exists() else 0.0)
