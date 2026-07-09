from pathlib import Path

import pandas as pd

from Backend.backend_utils import atomic_write_csv
from Servers.storage_paths import resolve_csv_path

def hybrid_score(csv_name: str, keyword_col: str, semantic_col: str, new_column_name: str = "hybrid_score", k: int = 60, csv_root: str | Path | None = None):
    print("Running Hybrid Reciprocal Rank Fusion (RRF)...")

    csv_path = resolve_csv_path(csv_name, csv_root)
    df = pd.read_csv(csv_path)

    keyword_rank = df[keyword_col].rank(ascending=False, method='min')
    semantic_rank = df[semantic_col].rank(ascending=False, method='min')

    rrf_score = (1.0 / (k + keyword_rank)) + (1.0 / (k + semantic_rank))

    df[new_column_name] = (rrf_score - rrf_score.min()) / (rrf_score.max() - rrf_score.min())

    atomic_write_csv(df, csv_path)
    print(f"Success! Hybrid RRF favorability saved to column '{new_column_name}'.")

if __name__ == "__main__":

    TARGET_NAME = "Space_Biology"

    hybrid_score(
        csv_name=TARGET_NAME,
        keyword_col="keyword_favorability",
        semantic_col="semantic_favorability",
        new_column_name="hybrid_favorability"
    )