from pathlib import Path

import pandas as pd


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "asc", "ascending")


def top_n_by_column(source_csv: str, output_csv: str, sort_column: str, n: int = 100, ascending=False, csv_root: str | Path | None = None):
    """Sort a CSV by `sort_column` and keep the top `n` rows, writing them to a new
    CSV. Unlike `numerical_filter` this is threshold-free -- e.g. "top 100 papers by
    favorability" regardless of the absolute score."""
    source_path = Path(csv_root) / f"{source_csv}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{source_csv}.csv")
    output_path = Path(csv_root) / f"{output_csv}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{output_csv}.csv")

    ascending = _as_bool(ascending)
    print(f"Selecting top {n} rows of '{source_csv}' by '{sort_column}' ({'ascending' if ascending else 'descending'})...")
    df = pd.read_csv(source_path)

    if sort_column not in df.columns:
        raise ValueError(f"Column '{sort_column}' was not found in the source dataset.")

    result = df.sort_values(by=sort_column, ascending=ascending).head(int(n))
    result.to_csv(output_path, index=False)
    print(f"Success! Wrote {len(result)} rows into '{output_csv}'.")


if __name__ == "__main__":
    top_n_by_column(
        source_csv="Space_Biology",
        output_csv="Top_100_Favorable",
        sort_column="hybrid_favorability",
        n=100,
    )
