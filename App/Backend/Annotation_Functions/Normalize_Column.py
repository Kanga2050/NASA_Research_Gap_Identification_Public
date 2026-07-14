from pathlib import Path

import pandas as pd

from Backend.backend_utils import atomic_write_csv
from Servers.storage_paths import resolve_csv_path


def normalize_column(csv_name: str, value_column: str, new_column_name: str = "", csv_root: str | Path | None = None):
    """Min-max scale a numeric column into the 0-1 range. If `new_column_name` is
    left blank (or equals `value_column`), the original column is overwritten in
    place with its normalized values; otherwise the scaled values land in a new
    column. A constant column normalizes to all-zeros."""
    csv_path = resolve_csv_path(csv_name, csv_root)

    print(f"Loading '{csv_name}.csv' to min-max scale column '{value_column}' to 0-1...")
    df = pd.read_csv(csv_path)

    if value_column not in df.columns:
        raise ValueError(f"Column '{value_column}' was not found in the CSV.")

    column = pd.to_numeric(df[value_column], errors="coerce")
    low, high = column.min(), column.max()
    print(f"Scaling {len(df):,} values from range [{low}, {high}] into [0, 1]...")
    if pd.isna(low) or high == low:
        normalized = column * 0
    else:
        normalized = (column - low) / (high - low)

    target = new_column_name.strip() if new_column_name and new_column_name.strip() else value_column
    df[target] = normalized

    atomic_write_csv(df, csv_path)
    if target == value_column:
        print(f"Success! Overwrote '{value_column}' in place with its 0-1 normalized values ({len(df):,} rows).")
    else:
        print(f"Success! Wrote 0-1 normalized values of '{value_column}' into new column '{target}' ({len(df):,} rows).")


if __name__ == "__main__":
    normalize_column(
        csv_name="Space_Biology",
        value_column="hybrid_favorability",
        new_column_name="hybrid_favorability_norm",
    )
