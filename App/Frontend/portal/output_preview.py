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
    "distance_map": {"category": "visualization", "kind": "html", "arg_index": 4},
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
        df = pd.read_csv(path, nrows=PREVIEW_ROW_LIMIT)
        preview.update(
            columns=list(df.columns),
            rows=[[_truncate(value) for value in row] for row in df.itertuples(index=False)],
            preview_row_count=len(df),
        )
    return preview
