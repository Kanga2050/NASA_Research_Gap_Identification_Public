from __future__ import annotations

import ast
import warnings

import pandas as pd

from App.Frontend.webapp.storage import (
    public_csv_root,
    public_paper_root,
    public_pdf_root,
    public_template_root,
    user_csv_root,
    user_paper_root,
    user_pdf_root,
    user_template_root,
)
from . import folders
from .file_meta import DESCRIPTIONS_FILE, read_descriptions
from .output_preview import resolve_safe_path

# How many rows to sample when inferring a column's wire type.
TYPE_SAMPLE_ROWS = 50

# Per import/export/describe/delete "kind": its default (primary) suffix and the
# per-user / shared-public root accessor. A "template" (Studio recipe) and a "paper"
# (Synthesize document) each may carry a second, rendered file -- its chart or its
# built report -- living right alongside it under the same stem (see TREE_SUFFIXES
# below); "html" is no longer a kind of its own; a chart/report is just the ".html"
# half of whichever kind it belongs to.
KIND_SUFFIX = {"csv": ".csv", "template": ".json", "paper": ".json"}
USER_ROOTS = {
    "csv": user_csv_root,
    "template": user_template_root,
    "paper": user_paper_root,
}
PUBLIC_ROOTS = {
    "csv": public_csv_root,
    "template": public_template_root,
    "paper": public_paper_root,
}
# All suffixes a folder-tree row for this kind may combine into one paired entry.
TREE_SUFFIXES = {
    "csv": (".csv",),
    "template": (".json", ".html"),
    "paper": (".json", ".html"),
}


def _list_names(folder, suffix: str) -> list[str]:
    """Stems of ``*suffix`` files anywhere in ``folder``'s tree (files live in nested
    subfolders now), excluding the descriptions sidecar. Names are unique within a type,
    so the bare stem is enough to resolve one -- which is what the Studio, the CSV
    pickers and the preview dropdowns list."""
    return sorted(
        p.stem for p in folder.rglob(f"*{suffix}") if p.name != DESCRIPTIONS_FILE
    )


def _list_with_descriptions(folder, suffixes) -> list[dict[str, str]]:
    if isinstance(suffixes, str):
        suffixes = (suffixes,)
    out: dict[str, dict] = {}
    sidecars: dict = {}
    for suffix in suffixes:
        for p in sorted(folder.rglob(f"*{suffix}")):
            if p.name == DESCRIPTIONS_FILE:
                continue
            if p.parent not in sidecars:
                sidecars[p.parent] = read_descriptions(p.parent)
            entry = out.setdefault(p.stem, {"name": p.stem,
                                            "description": sidecars[p.parent].get(p.stem, "")})
    result = list(out.values())
    result.sort(key=lambda d: d["name"].lower())
    return result


def list_user_tree(user, kind: str) -> dict:
    """The signed-in user's files of a kind, as a nested folder tree (for the Dashboard)."""
    return folders.list_tree(USER_ROOTS[kind](user), TREE_SUFFIXES[kind])


def list_public_tree(kind: str) -> dict:
    """The shared public library of a kind, as a nested folder tree."""
    return folders.list_tree(PUBLIC_ROOTS[kind](), TREE_SUFFIXES[kind])


def user_folder_paths(user, kind: str) -> list[str]:
    return folders.folder_paths(USER_ROOTS[kind](user))


def public_folder_paths(kind: str) -> list[str]:
    return folders.folder_paths(PUBLIC_ROOTS[kind]())


def list_user_csv_names(user) -> list[str]:
    return _list_names(user_csv_root(user), ".csv")


def list_user_html_names(user) -> list[str]:
    """Every chart/report .html the user owns -- charts live under the (merged)
    template root, built paper reports under the (merged) paper root."""
    return sorted(_list_names(user_template_root(user), ".html") +
                  _list_names(user_paper_root(user), ".html"))


def list_user_template_names(user) -> list[str]:
    return _list_names(user_template_root(user), ".json")


def list_user_paper_names(user) -> list[str]:
    return _list_names(user_paper_root(user), ".json")


def list_user_files(user, kind: str) -> list[dict[str, str]]:
    """[{"name","description"}] for the signed-in user's files of a given kind."""
    return _list_with_descriptions(USER_ROOTS[kind](user), TREE_SUFFIXES[kind])


def list_public(kind: str) -> list[dict[str, str]]:
    """[{"name","description"}] for the shared public library of a given kind."""
    return _list_with_descriptions(PUBLIC_ROOTS[kind](), TREE_SUFFIXES[kind])


# --- PDF collections (folders of PDFs, unlike the flat-file kinds above) -------
def _list_pdf_folders_in(base) -> list[dict]:
    """[{"name","count","description"}] for each subfolder of `base`.

    The description sidecar lives in `base` (keyed by folder name), the same shape
    the flat-file kinds use -- so a PDF collection carries a description through the
    library UI, publishing and pulling just like a CSV does.
    """
    if not base.is_dir():
        return []
    descriptions = read_descriptions(base)
    return [
        {
            "name": child.name,
            "count": len(list(child.glob("*.pdf"))),
            "description": descriptions.get(child.name, ""),
        }
        for child in sorted(base.iterdir())
        if child.is_dir()
    ]


def list_user_pdf_folders(user) -> list[dict]:
    return _list_pdf_folders_in(user_pdf_root(user))


def list_public_pdf_folders() -> list[dict]:
    return _list_pdf_folders_in(public_pdf_root())


def pdf_folder_choices(user) -> list[str]:
    """Collection names the user can chunk (their own first, then any public ones
    they don't already have a same-named folder for) -- for the task-form picker."""
    user_names = [f["name"] for f in list_user_pdf_folders(user)]
    seen = set(user_names)
    public_names = [f["name"] for f in list_public_pdf_folders() if f["name"] not in seen]
    return user_names + public_names


def _is_embedding_cell(value) -> bool:
    """A cell holds a (multi-dimensional) embedding when it stringifies a Python
    list with more than one element -- how Embed_Text/Reduce_Dimensionality store
    vectors. A single-element list is treated as a plain number, not an embedding."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not (text.startswith("[") and text.endswith("]")):
        return False
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return False
    return isinstance(parsed, (list, tuple)) and len(parsed) > 1


def infer_column_type(series: pd.Series) -> str:
    """Infer a wire type for a column: 'embedding' | 'number' | 'date' | 'text'.

    Order matters: numbers are checked before dates so an integer year (2015) is a
    number, while an ISO-8601 string ('2015-03-01') -- which is not purely numeric --
    falls through to 'date'. This mirrors the Studio wire-type table.
    """
    sample = series.dropna().head(TYPE_SAMPLE_ROWS)
    if len(sample) == 0:
        return "text"
    if sample.map(_is_embedding_cell).mean() >= 0.5:
        return "embedding"
    if pd.to_numeric(sample, errors="coerce").notna().mean() >= 0.8:
        return "number"
    with warnings.catch_warnings():
        # Freeform text reaches this check; dateutil's per-element fallback warns noisily.
        warnings.simplefilter("ignore")
        if pd.to_datetime(sample, errors="coerce").notna().mean() >= 0.8:
            return "date"
    return "text"


def list_csv_columns_typed(user, csv_name: str) -> list[dict[str, str]]:
    """Return each column as {"name", "type"} with an inferred wire type, for the
    Studio node editor. Reads a small row sample once to classify every column."""
    csv_path = resolve_safe_path(user_csv_root(user), csv_name, ".csv")
    if csv_path is None or not csv_path.exists():
        return []
    df = pd.read_csv(csv_path, nrows=TYPE_SAMPLE_ROWS)
    return [{"name": str(col), "type": infer_column_type(df[col])} for col in df.columns]
