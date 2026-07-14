from pathlib import Path

import pandas as pd

from Servers.storage_paths import resolve_csv_path


def cross_tab(source_csv: str, output_csv: str, row_column: str, column_column: str, csv_root: str | Path | None = None):
    """Build a contingency table counting how many rows fall into each
    (row_column, column_column) pairing. The output CSV has `row_column` as its
    first column and one numeric column per distinct `column_column` value --
    the matrix form a `heatmap` expects."""
    source_path = resolve_csv_path(source_csv, csv_root)
    output_path = resolve_csv_path(output_csv, csv_root)

    print(f"Loading '{source_csv}.csv' to cross-tabulate '{row_column}' (rows) against '{column_column}' (columns)...")
    df = pd.read_csv(source_path)

    for column in (row_column, column_column):
        if column not in df.columns:
            raise ValueError(f"Column '{column}' was not found in the source dataset.")

    print(f"Counting {len(df):,} rows into a contingency matrix...")
    table = pd.crosstab(df[row_column], df[column_column])
    table.reset_index().to_csv(output_path, index=False)
    print(f"Success! Wrote a {table.shape[0]}×{table.shape[1]} count matrix ('{row_column}' vs '{column_column}') → new file '{output_csv}.csv'.")


if __name__ == "__main__":
    cross_tab(
        source_csv="Combined_Corpus",
        output_csv="Source_By_Topic",
        row_column="source",
        column_column="topic_id",
    )
