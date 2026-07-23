import os
from pathlib import Path


def default_csv_root() -> Path:
    return Path("./App/Backend/CSVs")


def default_pdf_root() -> Path:
    """The shared public PDF library (collections of PDFs)."""
    return Path("./App/Backend/PDFs")


def default_html_root() -> Path:
    return Path("./App/Backend/Visualizations")


def default_template_root() -> Path:
    return Path("./App/Backend/Templates")


def resolve_csv_root(storage_root: str | Path | None = None) -> Path:
    if storage_root is None:
        return default_csv_root()
    return Path(storage_root)


def resolve_html_root(storage_root: str | Path | None = None) -> Path:
    if storage_root is None:
        return default_html_root()
    return Path(storage_root)


def _find_in_tree(root: Path, name: str, suffix: str) -> Path:
    """Locate ``<name><suffix>`` for a task. Files are organised into real subfolders
    (``csvs/Corpora/Space_Biology.csv``) but a pipeline still names its data by the bare
    stem, so we resolve a name that already exists anywhere in ``root``'s tree to that
    path (re-runs and downstream reads follow the file into its folder), and default a
    brand-new name to ``root/<name><suffix>``. A name that itself carries a path segment
    is honoured as given, reduced so it cannot climb out of ``root``."""
    root = Path(root)
    raw = str(name)
    if "/" in raw or "\\" in raw:
        parts = [p for p in raw.replace("\\", "/").split("/") if p not in ("", ".", "..")]
        return root.joinpath(*parts).with_name(f"{parts[-1]}{suffix}") if parts \
            else root / f"{name}{suffix}"
    direct = root / f"{name}{suffix}"
    if direct.exists():
        return direct
    target = f"{name}{suffix}"
    if root.is_dir():
        for found in sorted(root.rglob(target)):
            return found
    return direct


def resolve_csv_path(csv_name: str, csv_root: str | Path | None = None) -> Path:
    return _find_in_tree(resolve_csv_root(csv_root), csv_name, ".csv")


def resolve_html_path(output_name: str, html_root: str | Path | None = None) -> Path:
    return _find_in_tree(resolve_html_root(html_root), output_name, ".html")


def resolve_pdf_root(pdf_root: str | Path | None = None) -> Path:
    if pdf_root is None:
        return default_pdf_root()
    return Path(pdf_root)


def resolve_pdf_folder(folder_name: str, pdf_root: str | Path | None = None) -> Path | None:
    """Resolve a PDF *collection* name to a directory, checking the caller's
    `pdf_root` (the user's own pdfs area) first, then the public library. The name
    is reduced to a single path segment so a web/MCP/API caller can never traverse
    out of these roots. Returns None if no such collection exists."""
    safe = os.path.basename(str(folder_name).strip().rstrip("/\\"))
    if not safe or safe in {".", ".."}:
        return None
    for base in (resolve_pdf_root(pdf_root), default_pdf_root()):
        candidate = base / safe
        if candidate.is_dir():
            return candidate
    return None