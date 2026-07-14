"""Helpers shared across the Import/Annotation/Distillation/Visualization functions.

Every pipeline function follows the same shape -- resolve a path, load a CSV, check
the columns it was pointed at actually exist, do its work, write the result back --
so that shape lives here once instead of being retyped in each of the thirty-odd
functions.
"""
from __future__ import annotations

import ast
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from App.Servers.storage_paths import resolve_csv_path, resolve_html_path


# --------------------------------------------------------------------------- #
# Progress reporting
#
# The task feed only ever surfaces the LATEST printed line, so progress is emitted
# as a single line that is reprinted as work advances -- which makes it animate in
# place rather than scroll.
# --------------------------------------------------------------------------- #
def render_bar(current: int, total: int, width: int = 22) -> str:
    """A plain-text progress bar like ``█████████░░░░░░░░░░░░░`` sized to ``width``."""
    total = max(int(total), 1)
    current = min(max(int(current), 0), total)
    filled = int(current / total * width)
    return "█" * filled + "░" * (width - filled)


def progress_line(label: str, current: int, total: int, width: int = 22) -> str:
    """One-line progress string: ``<label> [bar]  42.0%  (420/1,000)``."""
    total = max(int(total), 1)
    current = min(max(int(current), 0), total)
    return f"{label} [{render_bar(current, total, width)}] {current / total * 100:5.1f}%  ({current:,}/{total:,})"


class ProgressReporter:
    """Emits a single-line progress bar the task feed picks up live. Prints are
    throttled so a tight loop never floods the log: a fresh line is emitted only once
    the bar has advanced by ``step`` (a fraction of the whole) AND ``min_interval``
    seconds have passed -- and always once the final item lands, so the bar is
    guaranteed to finish at 100%.

    Usage:
        reporter = ProgressReporter("Embedding abstracts", len(rows))
        for i, row in enumerate(rows, start=1):
            ...
            reporter.update(i)
    """

    def __init__(self, label: str, total: int, *, width: int = 22, step: float = 0.02, min_interval: float = 0.15):
        self.label = label
        self.total = max(int(total), 1)
        self.width = width
        self.step = step
        self.min_interval = min_interval
        self._last_fraction = -1.0
        self._last_time = 0.0

    def update(self, current: int) -> None:
        current = min(max(int(current), 0), self.total)
        fraction = current / self.total
        now = time.monotonic()
        is_last = current >= self.total
        advanced_enough = fraction - self._last_fraction >= self.step
        waited_enough = now - self._last_time >= self.min_interval
        if not is_last and not (advanced_enough and waited_enough):
            return
        self._last_fraction = fraction
        self._last_time = now
        print(progress_line(self.label, current, self.total, self.width))


# --------------------------------------------------------------------------- #
# Loading, validating and saving CSVs
# --------------------------------------------------------------------------- #
def require_columns(df: pd.DataFrame, *columns: str) -> None:
    """Fail cleanly if any named column is missing. Blank names are ignored, so an
    optional column can be passed straight through: ``require_columns(df, x, color)``.

    Without this a missing column surfaces as a bare pandas KeyError, which reaches
    the user as an unreadable task error.
    """
    missing = [c for c in columns if c and c not in df.columns]
    if missing:
        available = ", ".join(map(str, df.columns))
        raise ValueError(
            f"Column{'s' if len(missing) > 1 else ''} {', '.join(repr(c) for c in missing)} "
            f"not found in the CSV. Available columns: {available}"
        )


def load_csv(csv_name: str, csv_root=None, *, columns: tuple[str, ...] = (), **read_kwargs) -> pd.DataFrame:
    """Read ``<csv_name>.csv`` from the caller's CSV root and check that ``columns``
    all exist. Raises a clear ValueError when the file or a column is missing."""
    csv_path = resolve_csv_path(csv_name, csv_root)
    if not Path(csv_path).exists():
        raise ValueError(f"No CSV named '{csv_name}' in this workspace.")
    df = pd.read_csv(csv_path, **read_kwargs)
    if columns:
        require_columns(df, *columns)
    return df


def save_csv(df: pd.DataFrame, csv_name: str, csv_root=None) -> None:
    """Write ``df`` to ``<csv_name>.csv`` via a temp file + atomic rename, so a crash
    or a concurrent read mid-write never sees a half-written file at the real path."""
    csv_path = resolve_csv_path(csv_name, csv_root)
    temp_path = Path(f"{csv_path}.tmp")
    df.to_csv(temp_path, index=False)
    os.replace(temp_path, csv_path)


def write_chart(fig, output_name: str, html_root=None, summary: str = "Chart") -> None:
    """Write a Plotly figure to ``<output_name>.html`` and report it as the task's
    final line (which is what the dashboard surfaces when the task completes)."""
    fig.write_html(resolve_html_path(output_name, html_root))
    print(f"Success! {summary} saved to '{output_name}.html'.")


# --------------------------------------------------------------------------- #
# Value coercion
# --------------------------------------------------------------------------- #
_TRUTHY = {"true", "1", "yes", "on", "drop", "asc", "ascending"}


def as_bool(value) -> bool:
    """Coerce a checkbox/JSON/form value to a bool. Studio and the REST API both send
    booleans as strings, so "true"/"1"/"yes" must read as True."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUTHY


def parse_vector(value) -> np.ndarray:
    """Parse one stored embedding/coordinate cell ("[0.1, 0.2, ...]") into a vector."""
    return np.asarray(ast.literal_eval(value), dtype=float)


def stacked_vectors(series: pd.Series) -> np.ndarray:
    """Stack a column of stringified vectors into a single (n_rows × n_dims) matrix."""
    return np.vstack(series.apply(parse_vector).values)


def drop_excluded(df: pd.DataFrame, column: str, exclude: str) -> pd.DataFrame:
    """Drop rows whose `column` value (compared as text) is in the comma-separated
    `exclude` list -- e.g. "-1" to omit the HDBSCAN noise cluster from a chart."""
    if not exclude:
        return df
    drop = {value.strip() for value in str(exclude).split(",") if value.strip()}
    return df[~df[column].astype(str).isin(drop)]


def count_or_sum(df: pd.DataFrame, group_cols: list[str], value_column: str) -> tuple[pd.DataFrame, str]:
    """Aggregate `df` by `group_cols`, either counting rows or summing `value_column`.

    The "no value column means count the rows" convention is what bar_chart and
    pie_chart both offer. Returns the aggregated frame and the name of the column
    holding the measure.
    """
    if value_column:
        require_columns(df, value_column)
        data = df.groupby(group_cols, dropna=False)[value_column].sum().reset_index()
        return data, value_column
    data = df.groupby(group_cols, dropna=False).size().reset_index(name="count")
    return data, "count"


# --------------------------------------------------------------------------- #
# Vector maths
# --------------------------------------------------------------------------- #
def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return matrix / norms


def cosine_similarity_dense(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Cosine similarity between each row of `a` and each row of `b` (dense arrays,
    e.g. sentence embeddings) -- sklearn.metrics.pairwise.cosine_similarity without
    pulling in scikit-learn for a handful of lines."""
    return _l2_normalize(a) @ _l2_normalize(b).T
