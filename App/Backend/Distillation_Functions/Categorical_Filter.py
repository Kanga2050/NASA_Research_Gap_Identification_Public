from pathlib import Path

import pandas as pd

from Servers.storage_paths import resolve_csv_path


def categorical_filter(source_csv: str, output_csv: str, target_column: str, expected_value, csv_root: str | Path | None = None):
    """Keep only the rows whose `target_column` exactly equals `expected_value`,
    writing them to a brand new CSV. Comparison is done as strings so a value the
    user typed (e.g. topic id "1") matches regardless of the column's dtype."""
    source_path = resolve_csv_path(source_csv, csv_root)
    output_path = resolve_csv_path(output_csv, csv_root)

    print(f"Loading '{source_csv}.csv' to keep rows where {target_column} == {expected_value!r}...")
    df = pd.read_csv(source_path)

    if target_column not in df.columns:
        raise ValueError(f"Column '{target_column}' was not found in the source dataset.")

    print(f"Scanning {len(df):,} rows for exact matches...")
    matched = df[df[target_column].astype(str) == str(expected_value)]

    matched.to_csv(output_path, index=False)
    print(f"Success! Extracted {len(matched):,} of {len(df):,} rows where {target_column} == {expected_value!r} → new file '{output_csv}.csv'.")


if __name__ == "__main__":
    categorical_filter(
        source_csv="Space_Biology",
        output_csv="Topic_1",
        target_column="topic_id",
        expected_value=1,
    )
