from __future__ import annotations

import ast
import warnings

import pandas as pd

from App.Frontend.webapp.storage import user_csv_root, user_html_root
from .output_preview import resolve_safe_path

# How many rows to sample when inferring a column's wire type.
TYPE_SAMPLE_ROWS = 50


def list_user_csv_names(user) -> list[str]:
    return sorted(p.stem for p in user_csv_root(user).glob("*.csv"))


def list_user_html_names(user) -> list[str]:
    return sorted(p.stem for p in user_html_root(user).glob("*.html"))


def list_csv_columns(user, csv_name: str) -> list[str]:
    csv_path = resolve_safe_path(user_csv_root(user), csv_name, ".csv")
    if csv_path is None or not csv_path.exists():
        return []
    return list(pd.read_csv(csv_path, nrows=0).columns)


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
