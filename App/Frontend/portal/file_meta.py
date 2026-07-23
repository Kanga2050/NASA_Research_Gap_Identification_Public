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


# --- Folder-aware helpers: a file's description lives in the sidecar of the folder that
# actually contains it, so a bare (or foldered) file name resolves to the right sidecar.
def locate_file(type_root: Path, name: str, suffix: str) -> Path | None:
    """The on-disk path of ``name`` within a type's tree -- an explicit relative path if
    ``name`` carries one, else the bare stem searched recursively (names are unique)."""
    root = Path(type_root)
    raw = str(name)
    if "/" in raw or "\\" in raw:
        parts = [p for p in raw.replace("\\", "/").split("/") if p not in ("", ".", "..")]
        p = root.joinpath(*parts).with_name(f"{parts[-1]}{suffix}") if parts else None
        return p if p and p.exists() else None
    direct = root / f"{name}{suffix}"
    if direct.exists():
        return direct
    if root.is_dir():
        for found in sorted(root.rglob(f"{name}{suffix}")):
            return found
    return None


def find_description(type_root: Path, name: str, suffix: str) -> str:
    path = locate_file(type_root, name, suffix)
    return get_description(path.parent, path.stem) if path else ""


def store_description(type_root: Path, name: str, suffix: str, description: str) -> None:
    path = locate_file(type_root, name, suffix)
    if path:
        set_description(path.parent, path.stem, description)
