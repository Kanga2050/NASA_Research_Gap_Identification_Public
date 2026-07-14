from pathlib import Path

import pandas as pd

from Servers.storage_paths import resolve_csv_path


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "asc", "ascending")


def top_n_by_column(source_csv: str, output_csv: str, sort_column: str, n: int = 100, ascending=False, csv_root: str | Path | None = None):
    """Sort a CSV by `sort_column` and keep the top `n` rows, writing them to a new
    CSV. Unlike `numerical_filter` this is threshold-free -- e.g. "top 100 papers by
    favorability" regardless of the absolute score."""
    source_path = resolve_csv_path(source_csv, csv_root)
    output_path = resolve_csv_path(output_csv, csv_root)

    ascending = _as_bool(ascending)
    order = "smallest" if ascending else "largest"
    print(f"Loading '{source_csv}.csv' to take the top {int(n):,} rows by {order} '{sort_column}'...")
    df = pd.read_csv(source_path)

    if sort_column not in df.columns:
        raise ValueError(f"Column '{sort_column}' was not found in the source dataset.")

    print(f"Sorting {len(df):,} rows and keeping the top {int(n):,}...")
    result = df.sort_values(by=sort_column, ascending=ascending).head(int(n))
    result.to_csv(output_path, index=False)
    print(f"Success! Kept the top {len(result):,} of {len(df):,} rows by '{sort_column}' ({order} first) → new file '{output_csv}.csv'.")


if __name__ == "__main__":
    top_n_by_column(
        source_csv="Space_Biology",
        output_csv="Top_100_Favorable",
        sort_column="hybrid_favorability",
        n=100,
    )
