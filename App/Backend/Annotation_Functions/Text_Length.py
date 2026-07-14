from pathlib import Path

import pandas as pd

from Backend.backend_utils import atomic_write_csv
from Servers.storage_paths import resolve_csv_path


def text_length(csv_name: str, text_column: str, new_column_name: str = "length", unit: str = "words", csv_root: str | Path | None = None):
    """Add a numeric column measuring the length of `text_column`. `unit="words"`
    counts whitespace-separated tokens; `unit="chars"` counts characters. Useful as
    an axis for scatter plots (e.g. abstract length vs. favorability)."""
    csv_path = resolve_csv_path(csv_name, csv_root)

    print(f"Loading '{csv_name}.csv' to measure the length of column '{text_column}' in {unit}...")
    df = pd.read_csv(csv_path)

    if text_column not in df.columns:
        raise ValueError(f"Column '{text_column}' was not found in the CSV.")

    text = df[text_column].fillna("").astype(str)
    print(f"Counting {unit} for {len(df):,} rows...")
    if unit == "chars":
        df[new_column_name] = text.str.len()
    else:
        df[new_column_name] = text.str.split().apply(len)

    atomic_write_csv(df, csv_path)
    print(f"Success! Measured '{text_column}' length in {unit}; saved to column '{new_column_name}' for {len(df):,} rows.")


if __name__ == "__main__":
    text_length(
        csv_name="Space_Biology",
        text_column="abstract",
        new_column_name="abstract_length",
        unit="words",
    )
