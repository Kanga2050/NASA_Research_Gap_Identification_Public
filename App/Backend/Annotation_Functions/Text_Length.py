import os
from pathlib import Path

import pandas as pd


def text_length(csv_name: str, text_column: str, new_column_name: str = "length", unit: str = "words", csv_root: str | Path | None = None):
    """Add a numeric column measuring the length of `text_column`. `unit="words"`
    counts whitespace-separated tokens; `unit="chars"` counts characters. Useful as
    an axis for scatter plots (e.g. abstract length vs. favorability)."""
    csv_path = Path(csv_root) / f"{csv_name}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{csv_name}.csv")

    print(f"Measuring text length of '{text_column}' in '{csv_name}' ({unit})...")
    df = pd.read_csv(csv_path)

    if text_column not in df.columns:
        raise ValueError(f"Column '{text_column}' was not found in the CSV.")

    text = df[text_column].fillna("").astype(str)
    if unit == "chars":
        df[new_column_name] = text.str.len()
    else:
        df[new_column_name] = text.str.split().apply(len)

    temp_path = Path(str(csv_path) + ".tmp")
    df.to_csv(temp_path, index=False)
    os.replace(temp_path, csv_path)
    print(f"Success! Length saved to column '{new_column_name}'.")


if __name__ == "__main__":
    text_length(
        csv_name="Space_Biology",
        text_column="abstract",
        new_column_name="abstract_length",
        unit="words",
    )
