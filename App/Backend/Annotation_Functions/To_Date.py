import warnings
from pathlib import Path

import pandas as pd

from Backend.backend_utils import atomic_write_csv
from Servers.storage_paths import resolve_csv_path


def to_date(csv_name: str, date_column: str, new_column_name: str = "date", csv_root: str | Path | None = None):
    """Normalize `date_column` into a canonical ISO-8601 date column (YYYY-MM-DD).

    ISO-8601 dates are monotonic under both string and datetime comparison, so the
    result is a proper "date" type that downstream numeric/range filtering, sorting
    and time-axis charts can use directly. Values pandas can't parse become blank.
    """
    csv_path = resolve_csv_path(csv_name, csv_root)

    print(f"Normalizing '{date_column}' in '{csv_name}' to ISO-8601 dates...")
    df = pd.read_csv(csv_path)

    if date_column not in df.columns:
        raise ValueError(f"Column '{date_column}' was not found in the CSV.")

    # format="mixed" parses each value independently, so heterogeneous inputs
    # ("2015-03-01", "March 2018", "2012/06/15") all resolve; unparseable -> NaT.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(df[date_column], errors="coerce", format="mixed")
    # strftime yields NaT -> "NaT"; blank those out so unparsed rows are empty, not junk.
    iso = parsed.dt.strftime("%Y-%m-%d")
    df[new_column_name] = iso.where(parsed.notna(), "")

    atomic_write_csv(df, csv_path)
    filled = int(parsed.notna().sum())
    print(f"Success! Wrote ISO dates for {filled}/{len(df)} rows into column '{new_column_name}'.")


if __name__ == "__main__":
    to_date(
        csv_name="Space_Biology",
        date_column="publish_time",
        new_column_name="date",
    )
