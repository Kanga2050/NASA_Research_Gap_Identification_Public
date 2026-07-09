"""Small helpers shared across Annotation/Distillation/Visualization functions."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd


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
