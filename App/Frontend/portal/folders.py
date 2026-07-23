"""Folders for the file libraries.

Each file *type* (csvs, html, templates, papers) is a root directory, and a user may
organise the files of one type into real nested subfolders. A folder therefore only
ever holds one type of data, which is why a folder can still live under its type's
root and be pushed/pulled as a unit.

File identity stays the bare stem (unique within a type), so a saved pipeline that
names its data ``Space_Biology`` keeps working wherever that CSV is filed -- the
resolvers in ``output_preview`` and ``App.Servers.storage_paths`` search the tree.
This module is the folder layer on top: it lists a type's tree, and creates, renames,
moves and deletes folders and files, carrying each file's description sidecar along.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .file_meta import (DESCRIPTIONS_FILE, get_description, read_descriptions,
                        remove_description, set_description)


class FolderError(ValueError):
    """A folder operation was rejected (bad name, escape attempt, or collision)."""


def _clean_segment(segment: str) -> str:
    seg = str(segment).strip().strip("/\\").strip()
    if not seg or seg in {".", ".."} or "/" in seg or "\\" in seg:
        raise FolderError(f"Invalid folder name: {segment!r}")
    if seg == DESCRIPTIONS_FILE or seg.startswith("_descriptions"):
        raise FolderError("That name is reserved.")
    return seg


def safe_dir(root: Path, relpath: str = "") -> Path:
    """Resolve a folder path relative to ``root``, rejecting anything that escapes it.
    An empty ``relpath`` is the root itself."""
    root = Path(root).resolve()
    parts = [p for p in str(relpath or "").replace("\\", "/").split("/") if p not in ("", ".")]
    for p in parts:
        if p == "..":
            raise FolderError("Path escapes the library root.")
    target = root.joinpath(*parts).resolve() if parts else root
    if target != root and root not in target.parents:
        raise FolderError("Path escapes the library root.")
    return target


# --------------------------------------------------------------------------- #
# Listing
# --------------------------------------------------------------------------- #
def list_tree(root: Path, suffix: str) -> dict:
    """The type's contents as a nested tree: every folder carries its own files (with
    descriptions from that folder's sidecar) and its subfolders, recursively."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    return _tree_of(root, root, suffix)


def _tree_of(root: Path, folder: Path, suffix: str) -> dict:
    rel = folder.relative_to(root).as_posix()
    rel = "" if rel == "." else rel
    descriptions = read_descriptions(folder)
    files, subfolders = [], []
    for child in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if child.name == DESCRIPTIONS_FILE:
            continue
        if child.is_dir():
            subfolders.append(_tree_of(root, child, suffix))
        elif child.suffix == suffix:
            stem = child.stem
            files.append({"name": stem,
                          "path": (f"{rel}/{stem}" if rel else stem),
                          "folder": rel,
                          "description": descriptions.get(stem, "")})
    name = folder.name if rel else ""
    return {"name": name, "path": rel, "folders": subfolders, "files": files}


def folder_paths(root: Path) -> list[str]:
    """Every folder in the tree as a relative path (root first as ""), for a
    'place this in which folder?' picker."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    out = [""]
    for child in sorted(root.rglob("*")):
        if child.is_dir():
            out.append(child.relative_to(root).as_posix())
    return out


# --------------------------------------------------------------------------- #
# Mutations
# --------------------------------------------------------------------------- #
def create_folder(root: Path, parent: str, name: str) -> str:
    """Create ``name`` inside folder ``parent`` (relative). Returns the new relpath."""
    parent_dir = safe_dir(root, parent)
    seg = _clean_segment(name)
    target = parent_dir / seg
    if target.exists():
        raise FolderError(f"A folder named {seg!r} is already here.")
    target.mkdir(parents=True)
    return target.relative_to(Path(root).resolve()).as_posix()


def delete_folder(root: Path, relpath: str) -> None:
    """Delete a folder and everything under it."""
    target = safe_dir(root, relpath)
    if target == Path(root).resolve():
        raise FolderError("Cannot delete the library root.")
    if not target.is_dir():
        raise FolderError("No such folder.")
    shutil.rmtree(target)


def rename_folder(root: Path, relpath: str, new_name: str) -> str:
    """Rename a folder in place. Returns the new relpath."""
    target = safe_dir(root, relpath)
    if target == Path(root).resolve():
        raise FolderError("Cannot rename the library root.")
    seg = _clean_segment(new_name)
    dest = target.parent / seg
    if dest.exists():
        raise FolderError(f"A folder named {seg!r} is already here.")
    target.rename(dest)
    return dest.relative_to(Path(root).resolve()).as_posix()


def _unique(dest_dir: Path, stem: str, suffix: str) -> tuple[Path, str]:
    candidate = dest_dir / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate, stem
    i = 2
    while True:
        alt_stem = f"{stem}_{i}"
        alt = dest_dir / f"{alt_stem}{suffix}"
        if not alt.exists():
            return alt, alt_stem
        i += 1


def _locate_file(root: Path, name: str, suffix: str) -> Path | None:
    """The on-disk path of file ``name`` (bare stem searched in the tree, or an explicit
    relative path)."""
    root = Path(root).resolve()
    raw = str(name)
    if "/" in raw or "\\" in raw:
        parts = [p for p in raw.replace("\\", "/").split("/") if p not in ("", ".", "..")]
        p = root.joinpath(*parts).with_name(f"{parts[-1]}{suffix}") if parts else None
        return p if p and p.exists() else None
    direct = root / f"{name}{suffix}"
    if direct.exists():
        return direct
    for found in sorted(root.rglob(f"{name}{suffix}")):
        return found
    return None


def move_file(root: Path, name: str, suffix: str, dest_folder: str) -> str:
    """Move a file (found by name) into ``dest_folder``, carrying its description.
    Returns the file's new relpath."""
    src = _locate_file(root, name, suffix)
    if src is None:
        raise FolderError("No such file.")
    dest_dir = safe_dir(root, dest_folder)
    dest_dir.mkdir(parents=True, exist_ok=True)
    if src.parent.resolve() == dest_dir.resolve():
        return src.relative_to(Path(root).resolve()).with_suffix("").as_posix()
    dest, final_stem = _unique(dest_dir, src.stem, suffix)
    description = get_description(src.parent, src.stem)
    shutil.move(str(src), str(dest))
    remove_description(src.parent, src.stem)
    if description:
        set_description(dest_dir, final_stem, description)
    return dest.relative_to(Path(root).resolve()).with_suffix("").as_posix()


def move_folder(root: Path, relpath: str, dest_folder: str) -> str:
    """Move a whole folder into ``dest_folder``. Returns the new relpath."""
    src = safe_dir(root, relpath)
    root_resolved = Path(root).resolve()
    if src == root_resolved:
        raise FolderError("Cannot move the library root.")
    dest_parent = safe_dir(root, dest_folder)
    if dest_parent == src or src in dest_parent.parents:
        raise FolderError("Cannot move a folder into itself.")
    dest = dest_parent / src.name
    if dest.exists():
        raise FolderError(f"A folder named {src.name!r} is already there.")
    dest_parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return dest.relative_to(root_resolved).as_posix()
