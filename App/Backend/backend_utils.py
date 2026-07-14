"""Small helpers shared across Annotation/Distillation/Visualization functions."""
from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pandas as pd


def render_bar(current: int, total: int, width: int = 22) -> str:
    """Return a plain-text progress bar like ``█████████░░░░░░░░░░░░░`` sized to
    ``width`` characters. The live task feed only ever shows the *latest* printed
    line, so reprinting this string as work advances makes it animate in place."""
    total = max(int(total), 1)
    current = min(max(int(current), 0), total)
    filled = int(current / total * width)
    return "█" * filled + "░" * (width - filled)


def progress_line(label: str, current: int, total: int, width: int = 22) -> str:
    """One-line progress string: ``<label> [bar]  42.0%  (420/1,000)``. Kept to a
    single line because the frontend surfaces only the most recent print."""
    total = max(int(total), 1)
    current = min(max(int(current), 0), total)
    pct = current / total * 100
    return f"{label} [{render_bar(current, total, width)}] {pct:5.1f}%  ({current:,}/{total:,})"


class ProgressReporter:
    """Emits a single-line textual progress bar to stdout that the task feed picks
    up live. Prints are throttled so a tight loop never floods the log: a fresh
    line is emitted only once the bar has advanced by ``step`` (fraction of the
    whole) or at least ``min_interval`` seconds have passed -- and always once the
    final item lands, so the bar is guaranteed to finish at 100%.

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


def atomic_write_csv(df: pd.DataFrame, csv_path: str | Path) -> None:
    """Write `df` to `csv_path` via a temp file + atomic rename, so a crash or
    concurrent read mid-write never sees a partial file at the real path."""
    temp_path = Path(f"{csv_path}.tmp")
    df.to_csv(temp_path, index=False)
    os.replace(temp_path, csv_path)


def drop_excluded(df: pd.DataFrame, column: str, exclude: str) -> pd.DataFrame:
    """Drop rows whose `column` value (compared as text) is in the comma-separated
    `exclude` list -- e.g. "-1" to omit the HDBSCAN noise cluster from a chart."""
    if not exclude:
        return df
    drop = {value.strip() for value in str(exclude).split(",") if value.strip()}
    return df[~df[column].astype(str).isin(drop)]


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return matrix / norms


def cosine_similarity_dense(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Cosine similarity between each row of `a` and each row of `b` (dense arrays,
    e.g. sentence embeddings) -- sklearn.metrics.pairwise.cosine_similarity without
    pulling in scikit-learn for a handful of lines."""
    return _l2_normalize(a) @ _l2_normalize(b).T
