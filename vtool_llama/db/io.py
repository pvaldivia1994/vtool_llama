"""
io.py — Utilidades compartidas de I/O para archivos y datos.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_json_dict(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def read_json(path: Path, dataclass_type: type) -> dict:
    data = read_json_dict(path)
    valid = {}
    for f in dataclass_type.__dataclass_fields__:
        if f in data:
            valid[f] = data[f]
    return valid


def write_json(path: Path, data: dict, atomic: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if atomic:
        temp_path = path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, path)
        except Exception as e:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise e
    else:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
