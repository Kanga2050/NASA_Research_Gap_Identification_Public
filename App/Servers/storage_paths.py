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


def resolve_csv_path(csv_name: str, csv_root: str | Path | None = None) -> Path:
    return resolve_csv_root(csv_root) / f"{csv_name}.csv"


def resolve_html_path(output_name: str, html_root: str | Path | None = None) -> Path:
    return resolve_html_root(html_root) / f"{output_name}.html"


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