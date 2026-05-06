# ---------------------------------------------------------
# core/file_io.py
# Safe JSON read/write helpers - replaces inline fs.readFileSync patterns
# ---------------------------------------------------------
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def read_json(path: str | Path, fallback: Any = None) -> Any:
    """
    Safely read and parse a JSON file.
    Returns `fallback` if the file doesn't exist or is malformed.
    Default fallback is an empty list (mirrors JS readJSON pattern).
    """
    if fallback is None:
        fallback = []
    filepath = Path(path)
    if not filepath.exists():
        return fallback
    try:
        content = filepath.read_text(encoding="utf-8").strip()
        if not content:
            return fallback
        return json.loads(content)
    except (json.JSONDecodeError, OSError):
        return fallback


def write_json(path: str | Path, data: Any) -> None:
    """
    Atomically write data as formatted JSON.
    Writes to a .tmp file then renames (mirrors atomic write in call_server.js).
    """
    filepath = Path(path)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    tmp = filepath.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(filepath))
    except OSError as e:
        print(f"❌ write_json failed for {filepath}: {e}")
        # Don't raise – keep server alive (matches JS behaviour)
