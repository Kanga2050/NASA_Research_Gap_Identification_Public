"""Per-folder file descriptions, stored as a JSON sidecar.

Every storage folder (a user's ``csvs``/``html``/``templates`` folder, or one of
the shared public folders) may hold a ``_descriptions.json`` mapping a file's
*stem* (name without extension) to a human-readable description. A sidecar is
used rather than a DB model because it works identically for user-owned folders
and the ownerless public commons, and it travels naturally when a file is copied
between folders (import / publish carry the description along).
"""

from __future__ import annotations

import json
from pathlib import Path

DESCRIPTIONS_FILE = "_descriptions.json"


def _sidecar_path(folder: Path) -> Path:
    return Path(folder) / DESCRIPTIONS_FILE


def read_descriptions(folder: Path) -> dict[str, str]:
    """Return the {name: description} map for a folder, tolerant of a missing or
    corrupt sidecar (returns an empty dict rather than raising)."""
    path = _sidecar_path(folder)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def _write_descriptions(folder: Path, data: dict[str, str]) -> None:
    path = _sidecar_path(folder)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def get_description(folder: Path, name: str) -> str:
    return read_descriptions(folder).get(name, "")


def set_description(folder: Path, name: str, description: str) -> None:
    """Set (or clear, when blank) the description for ``name`` in ``folder``."""
    data = read_descriptions(folder)
    description = (description or "").strip()
    if description:
        data[name] = description
    else:
        data.pop(name, None)
    _write_descriptions(folder, data)


def remove_description(folder: Path, name: str) -> None:
    data = read_descriptions(folder)
    if name in data:
        data.pop(name, None)
        _write_descriptions(folder, data)
