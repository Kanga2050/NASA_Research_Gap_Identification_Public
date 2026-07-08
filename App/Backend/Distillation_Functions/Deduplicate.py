from pathlib import Path

import pandas as pd


def deduplicate(source_csv: str, output_csv: str, subset_column: str, csv_root: str | Path | None = None):
    """Drop rows that repeat a value in `subset_column`, keeping the first
    occurrence, and write the de-duplicated rows to a new CSV (e.g. dedupe papers
    by title or doi)."""
    source_path = Path(csv_root) / f"{source_csv}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{source_csv}.csv")
    output_path = Path(csv_root) / f"{output_csv}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{output_csv}.csv")

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
