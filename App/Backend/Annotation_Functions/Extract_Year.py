import os
from pathlib import Path

import pandas as pd


def extract_year(csv_name: str, date_column: str, new_column_name: str = "year", csv_root: str | Path | None = None):
    """Parse a four-digit year out of `date_column` into a new numeric column.
    Tries full date parsing first, then falls back to the first 4-digit run for any
    values pandas can't parse. Unlocks temporal charts (e.g. publications per year)."""
    csv_path = Path(csv_root) / f"{csv_name}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{csv_name}.csv")

    print(f"Extracting year from '{date_column}' in '{csv_name}'...")
    df = pd.read_csv(csv_path)

    if date_column not in df.columns:
        raise ValueError(f"Column '{date_column}' was not found in the CSV.")

    parsed = pd.to_datetime(df[date_column], errors="coerce")
    years = parsed.dt.year

    # Fallback for values pandas couldn't parse: grab the first 4-digit run.
    unparsed = years.isna()
    if unparsed.any():
        extracted = df.loc[unparsed, date_column].astype(str).str.extract(r"(\d{4})")[0]
        years.loc[unparsed] = pd.to_numeric(extracted, errors="coerce")

    df[new_column_name] = years.astype("Int64")

    temp_path = Path(str(csv_path) + ".tmp")
    df.to_csv(temp_path, index=False)
    os.replace(temp_path, csv_path)
    filled = int(df[new_column_name].notna().sum())
    print(f"Success! Extracted a year for {filled}/{len(df)} rows into column '{new_column_name}'.")


if __name__ == "__main__":
    extract_year(
        csv_name="Space_Biology",
        date_column="publish_time",
        new_column_name="year",
    )
