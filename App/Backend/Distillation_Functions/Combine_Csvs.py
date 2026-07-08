from pathlib import Path

import pandas as pd


def combine_csvs(source_csvs: str, output_csv: str, source_column: str = "source", csv_root: str | Path | None = None):
    """Stack several CSVs into one (outer-union of columns), adding `source_column`
    that tags every row with the name of the CSV it came from. `source_csvs` is a
    comma-separated list of CSV names, e.g. "Microgravity,Space_Crops"."""
    names = [name.strip() for name in str(source_csvs).split(",") if name.strip()]
    if len(names) < 2:
        raise ValueError("Provide at least two comma-separated CSV names to combine.")

    output_path = Path(csv_root) / f"{output_csv}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{output_csv}.csv")

    frames = []
    for name in names:
        source_path = Path(csv_root) / f"{name}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{name}.csv")
        print(f"Loading '{name}'...")
        part = pd.read_csv(source_path)
        part[source_column] = name
        frames.append(part)

    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined.to_csv(output_path, index=False)
    print(f"Success! Combined {len(names)} files into '{output_csv}' ({len(combined)} rows), tagged by '{source_column}'.")


if __name__ == "__main__":
    combine_csvs(
        source_csvs="Microgravity,Space Crops",
        output_csv="Combined_Corpus",
        source_column="source",
    )
