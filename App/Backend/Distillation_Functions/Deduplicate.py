from pathlib import Path

import pandas as pd

from Servers.storage_paths import resolve_csv_path


def deduplicate(source_csv: str, output_csv: str, subset_column: str, csv_root: str | Path | None = None):
    """Drop rows that repeat a value in `subset_column`, keeping the first
    occurrence, and write the de-duplicated rows to a new CSV (e.g. dedupe papers
    by title or doi)."""
    source_path = resolve_csv_path(source_csv, csv_root)
    output_path = resolve_csv_path(output_csv, csv_root)

    print(f"De-duplicating '{source_csv}' on '{subset_column}'...")
    df = pd.read_csv(source_path)

    if subset_column not in df.columns:
        raise ValueError(f"Column '{subset_column}' was not found in the source dataset.")

    before = len(df)
    result = df.drop_duplicates(subset=[subset_column])
    result.to_csv(output_path, index=False)
    print(f"Success! Removed {before - len(result)} duplicate rows; {len(result)} remain in '{output_csv}'.")


if __name__ == "__main__":
    deduplicate(
        source_csv="Space_Biology",
        output_csv="Space_Biology_Unique",
        subset_column="title",
    )
