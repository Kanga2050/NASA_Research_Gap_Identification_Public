from pathlib import Path

import pandas as pd


def cross_tab(source_csv: str, output_csv: str, row_column: str, column_column: str, csv_root: str | Path | None = None):
    """Build a contingency table counting how many rows fall into each
    (row_column, column_column) pairing. The output CSV has `row_column` as its
    first column and one numeric column per distinct `column_column` value --
    the matrix form a `heatmap` expects."""
    source_path = Path(csv_root) / f"{source_csv}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{source_csv}.csv")
    output_path = Path(csv_root) / f"{output_csv}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{output_csv}.csv")

    print(f"Cross-tabulating '{row_column}' against '{column_column}' in '{source_csv}'...")
    df = pd.read_csv(source_path)

    for column in (row_column, column_column):
        if column not in df.columns:
            raise ValueError(f"Column '{column}' was not found in the source dataset.")

    table = pd.crosstab(df[row_column], df[column_column])
    table.reset_index().to_csv(output_path, index=False)
    print(f"Success! Wrote a {table.shape[0]}x{table.shape[1]} count matrix into '{output_csv}'.")


if __name__ == "__main__":
    cross_tab(
        source_csv="Combined_Corpus",
        output_csv="Source_By_Topic",
        row_column="source",
        column_column="topic_id",
    )
