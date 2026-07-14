from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from App.Frontend.webapp.storage import user_csv_root, user_html_root
from .models import TaskRecord

PREVIEW_ROW_LIMIT = 50
CELL_CHAR_LIMIT = 200

# Maps a queued function to where its output lives: which positional arg
# holds the output file's name, and whether that output is a csv or html file.
FUNCTION_OUTPUT_META = {
    "embed_text": {"category": "annotation", "kind": "csv", "arg_index": 0},
    "reduce_dimensionality": {"category": "annotation", "kind": "csv", "arg_index": 0},
    "cluster": {"category": "annotation", "kind": "csv", "arg_index": 0},
    "keyword_score": {"category": "annotation", "kind": "csv", "arg_index": 0},
    "semantic_score": {"category": "annotation", "kind": "csv", "arg_index": 0},
    "hybrid_score": {"category": "annotation", "kind": "csv", "arg_index": 0},
    "numerical_filter": {"category": "distillation", "kind": "csv", "arg_index": 1},
    "openalex_scraper": {"category": "distillation", "kind": "csv", "arg_index": 1},
    "chunk_pdfs": {"category": "distillation", "kind": "csv", "arg_index": 1},
    "distance_map": {"category": "visualization", "kind": "html", "arg_index": 4},
    # Distillation (output CSV name is the 2nd positional arg)
    "categorical_filter": {"category": "distillation", "kind": "csv", "arg_index": 1},
    "combine_csvs": {"category": "distillation", "kind": "csv", "arg_index": 1},
    "aggregate_dictionary": {"category": "distillation", "kind": "csv", "arg_index": 1},
    "group_aggregate": {"category": "distillation", "kind": "csv", "arg_index": 1},
    "top_n_by_column": {"category": "distillation", "kind": "csv", "arg_index": 1},
    "deduplicate": {"category": "distillation", "kind": "csv", "arg_index": 1},
    "select_columns": {"category": "distillation", "kind": "csv", "arg_index": 1},
    "cross_tab": {"category": "distillation", "kind": "csv", "arg_index": 1},
    "arithmetic": {"category": "distillation", "kind": "csv", "arg_index": 1},
    # Annotation (edits the source CSV in place; name is the 1st positional arg)
    "word_frequency": {"category": "annotation", "kind": "csv", "arg_index": 0},
    "label_topics": {"category": "annotation", "kind": "csv", "arg_index": 0},
    "text_length": {"category": "annotation", "kind": "csv", "arg_index": 0},
    "extract_year": {"category": "annotation", "kind": "csv", "arg_index": 0},
    "to_date": {"category": "annotation", "kind": "csv", "arg_index": 0},
    "normalize_column": {"category": "annotation", "kind": "csv", "arg_index": 0},
    "hierarchical_cluster": {"category": "annotation", "kind": "csv", "arg_index": 0},
    # Visualization (output HTML name position varies per function signature)
    "bar_chart": {"category": "visualization", "kind": "html", "arg_index": 5},
    "scatter_plot": {"category": "visualization", "kind": "html", "arg_index": 7},
    "histogram": {"category": "visualization", "kind": "html", "arg_index": 4},
    "line_chart": {"category": "visualization", "kind": "html", "arg_index": 5},
    "box_plot": {"category": "visualization", "kind": "html", "arg_index": 4},
    "heatmap": {"category": "visualization", "kind": "html", "arg_index": 5},
    "pie_chart": {"category": "visualization", "kind": "html", "arg_index": 4},
    "hierarchical_dendrogram": {"category": "visualization", "kind": "html", "arg_index": 4},
}

CATEGORY_LABELS = {
    "annotation": "Annotated CSV preview",
    "distillation": "New CSV preview",
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
    """Resolve `root/name+suffix`, rejecting anything that escapes `root`."""
    root_resolved = root.resolve()
    candidate = (root_resolved / f"{name}{suffix}").resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        return None
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
    meta = FUNCTION_OUTPUT_META.get(task.function_name)
    if meta is None:
        return None

    args = task.args_json or []
    if len(args) <= meta["arg_index"]:
        return None
    output_name = args[meta["arg_index"]]

    kind = meta["kind"]
    root = user_csv_root(user) if kind == "csv" else user_html_root(user)
    path = resolve_safe_path(root, output_name, f".{kind}")
    base = {"category": meta["category"], "kind": kind, "name": output_name}

    if path is None or not path.exists():
        return {**base, "missing": True}

    preview = {**base, "label": CATEGORY_LABELS[meta["category"]], "function_name": task.function_name}
    if kind == "csv":
        preview.update(_read_csv_preview(path))
    return preview


def build_named_preview(user, kind: str, name: str) -> dict[str, Any]:
    """Build a preview for an arbitrary existing CSV/HTML file the user owns,
    identified by name (rather than by the task that produced it). Powers the
    center-column "view a previous output" dropdown."""
    if kind not in ("csv", "html"):
        return {"kind": kind, "name": name, "missing": True}

    root = user_csv_root(user) if kind == "csv" else user_html_root(user)
    path = resolve_safe_path(root, name, f".{kind}")
    base = {"kind": kind, "name": name}
    if path is None or not path.exists():
        return {**base, "missing": True}

    if kind == "csv":
        return {**base, **_read_csv_preview(path)}
    return base  # HTML is rendered via the existing preview_output_html iframe endpoint
