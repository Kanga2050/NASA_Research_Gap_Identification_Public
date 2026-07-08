from pathlib import Path

import pandas as pd


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "drop")


def select_columns(source_csv: str, output_csv: str, columns: str, drop=False, csv_root: str | Path | None = None):
    """Write a new CSV that keeps only `columns` (comma-separated), or, when
    `drop` is true, keeps everything EXCEPT those columns. Handy for stripping a
    heavy embedding column before export, or slimming a table down to what a chart
    needs."""
    source_path = Path(csv_root) / f"{source_csv}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{source_csv}.csv")
    output_path = Path(csv_root) / f"{output_csv}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{output_csv}.csv")

    wanted = [col.strip() for col in str(columns).split(",") if col.strip()]
    if not wanted:
        raise ValueError("Provide at least one column name.")

    drop_mode = _as_bool(drop)
    print(f"{'Dropping' if drop_mode else 'Keeping'} columns {wanted} from '{source_csv}'...")
    df = pd.read_csv(source_path)

    missing = [col for col in wanted if col not in df.columns]
    if missing:
        raise ValueError(f"Columns not found in the source dataset: {missing}")

    result = df.drop(columns=wanted) if drop_mode else df[wanted]
    result.to_csv(output_path, index=False)
    print(f"Success! Wrote '{output_csv}' with {len(result.columns)} columns.")


if __name__ == "__main__":
    select_columns(
        source_csv="Space_Biology",
        output_csv="Space_Biology_Slim",
        columns="abstract_embedding,2d,5d",
        drop=True,
    )
