#!/usr/bin/env python3
"""Validate every form in content/forms/. Run from server/: `uv run python ../content/lint.py`."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
from app.content import load_form  # noqa: E402

root = Path(__file__).resolve().parent / "forms"
ok = True
for p in sorted(root.glob("*.yaml")):
    try:
        form = load_form(p)
        n_items = sum(len(t.items) for t in form.tasks)
        print(f"OK   {p.name}: {form.id} v{form.version} ({len(form.tasks)} tasks, {n_items} items)")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"FAIL {p.name}: {e}")
sys.exit(0 if ok else 1)
