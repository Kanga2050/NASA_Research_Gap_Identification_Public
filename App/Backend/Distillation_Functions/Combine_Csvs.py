from pathlib import Path

import pandas as pd

from Servers.storage_paths import resolve_csv_path


def combine_csvs(source_csvs: str, output_csv: str, source_column: str = "source", csv_root: str | Path | None = None):
    """Stack several CSVs into one (outer-union of columns), adding `source_column`
    that tags every row with the name of the CSV it came from. `source_csvs` is a
    comma-separated list of CSV names, e.g. "Microgravity,Space_Crops"."""
    names = [name.strip() for name in str(source_csvs).split(",") if name.strip()]
    if len(names) < 2:
        raise ValueError("Provide at least two comma-separated CSV names to combine.")

    output_path = resolve_csv_path(output_csv, csv_root)

    frames = []
    total_rows = 0
    for i, name in enumerate(names, start=1):
        source_path = resolve_csv_path(name, csv_root)
        part = pd.read_csv(source_path)
        part[source_column] = name
        frames.append(part)
        total_rows += len(part)
        print(f"Loaded {i}/{len(names)}: '{name}' ({len(part):,} rows, {total_rows:,} rows stacked so far)...")

    print(f"Concatenating {len(names)} files (outer-union of columns) and writing '{output_csv}.csv'...")
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined.to_csv(output_path, index=False)
    print(f"Success! Stacked {len(names)} files into '{output_csv}.csv' ({len(combined):,} rows), origin tagged in column '{source_column}'.")


if __name__ == "__main__":
    combine_csvs(
        source_csvs="Microgravity,Space Crops",
        output_csv="Combined_Corpus",
        source_column="source",
    )
