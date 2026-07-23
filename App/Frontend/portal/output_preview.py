from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from App.Backend import registry
from App.Frontend.webapp.storage import user_csv_root, user_paper_root, user_template_root
from .models import TaskRecord

PREVIEW_ROW_LIMIT = 50
CELL_CHAR_LIMIT = 200

# What the dashboard calls the output of each family of function. An import and a
# distillation both hand back a brand-new table, so they read the same.
CATEGORY_LABELS = {
    "annotation": "Annotated CSV preview",
    "distillation": "New CSV preview",
    "import": "New CSV preview",
    "visualization": "Visualization",
}


def get_latest_task(user) -> TaskRecord | None:
    return TaskRecord.objects.filter(user=user).order_by("-created_at").first()


def get_latest_completed_task(user) -> TaskRecord | None:
    return (
        TaskRecord.objects.filter(user=user, status=TaskRecord.Status.COMPLETED)
        .order_by("-finished_at")
        .first()
    )


def resolve_safe_path(root: Path, name: str, suffix: str) -> Path | None:
    """Resolve a file named ``name`` (with ``suffix``) inside ``root``, anywhere in its
    folder tree, rejecting anything that escapes ``root``.

    Files live in real subfolders now (``root/Corpora/Space_Biology.csv``) but a pipeline,
    a template load, or an export still refers to a file by its bare stem. So:

    * a ``name`` that carries a path (``Corpora/Space_Biology``) resolves exactly there;
    * a bare ``name`` that already exists at the root resolves there (fast path);
    * otherwise the tree is searched for ``<stem><suffix>`` and the first match wins --
      names are unique within a type, so this is unambiguous;
    * a bare ``name`` that exists nowhere resolves to ``root/name+suffix`` (the default
      home for a brand-new file), so writes still land somewhere sensible.

    Returns ``None`` only when the path would escape ``root``.
    """
    root_resolved = root.resolve()
    candidate = (root_resolved / f"{name}{suffix}").resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        return None
    has_sep = "/" in str(name) or "\\" in str(name)
    if candidate.exists() or has_sep:
        return candidate
    target = f"{Path(name).name}{suffix}"
    for found in sorted(root_resolved.rglob(target)):
        return found
    return candidate


def _truncate(value: Any) -> str:
    text = "" if pd.isna(value) else str(value)
    if len(text) > CELL_CHAR_LIMIT:
        return text[:CELL_CHAR_LIMIT] + "…"
    return text


def _read_csv_preview(path: Path) -> dict[str, Any]:
    """Read the first PREVIEW_ROW_LIMIT rows of a CSV into a JSON-friendly preview
    (column headers + truncated cell values). Shared by the task-driven preview and
    the "view any past output" endpoint."""
    df = pd.read_csv(path, nrows=PREVIEW_ROW_LIMIT)
    return {
        "columns": list(df.columns),
        "rows": [[_truncate(value) for value in row] for row in df.itertuples(index=False)],
        "preview_row_count": len(df),
    }


def build_output_preview(task: TaskRecord, user) -> dict[str, Any] | None:
    """Preview whatever file a finished task produced.

    Which of the task's positional args names that file is not a fact this module
    knows -- it comes from the registry, which owns the argument order in the first
    place, so the two cannot drift apart.
    """
    try:
        fn = registry.get(task.function_name)
    except KeyError:
        return None

    args = task.args_json or []
    if len(args) <= fn.output_index:
        return None
    output_name = args[fn.output_index]

    kind = fn.output_kind
    # Every chart-producing registry function writes into the (merged) template
    # root -- build_paper's report is a separate, non-registry code path.
    root = user_csv_root(user) if kind == "csv" else user_template_root(user)
    path = resolve_safe_path(root, output_name, f".{kind}")
    base = {"category": fn.category, "kind": kind, "name": output_name}

    if path is None or not path.exists():
        return {**base, "missing": True}

    preview = {**base, "label": CATEGORY_LABELS[fn.category], "function_name": task.function_name}
    if kind == "csv":
        preview.update(_read_csv_preview(path))
    return preview


def build_named_preview(user, kind: str, name: str) -> dict[str, Any]:
    """Build a preview for an arbitrary existing CSV/HTML file the user owns,
    identified by name (rather than by the task that produced it). Powers the
    center-column "view a previous output" dropdown."""
    if kind not in ("csv", "html"):
        return {"kind": kind, "name": name, "missing": True}

    base = {"kind": kind, "name": name}
    if kind == "csv":
        path = resolve_safe_path(user_csv_root(user), name, ".csv")
        if path is None or not path.exists():
            return {**base, "missing": True}
    else:
        # An .html name is either a chart (lives with its Studio recipe) or a
        # built paper report (lives with its document) -- try both roots.
        path = resolve_safe_path(user_template_root(user), name, ".html")
        if path is None or not path.exists():
            path = resolve_safe_path(user_paper_root(user), name, ".html")
        if path is None or not path.exists():
            return {**base, "missing": True}

    if kind == "csv":
        return {**base, **_read_csv_preview(path)}
    return base  # HTML is rendered via the existing preview_output_html iframe endpoint
