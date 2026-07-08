import warnings
from pathlib import Path

import pandas as pd

def numerical_filter(source_csv: str, output_csv: str, target_score_column: str, threshold: float, csv_root: str | Path | None = None):
    source_csv = Path(csv_root) / f"{source_csv}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{source_csv}.csv")
    output_csv = Path(csv_root) / f"{output_csv}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{output_csv}.csv")

    print(f"Filtering dataset on '{target_score_column}' with a minimum threshold of {threshold}...")
    df = pd.read_csv(source_csv)

    if target_score_column not in df.columns:
        raise ValueError(f"Score column '{target_score_column}' was not found in the source dataset.")

    column = df[target_score_column]
    # Prefer a numeric comparison when both the column and the threshold are numeric
    # (numbers spuriously "parse" as dates via epoch offsets, so numeric must win).
    # Otherwise treat it as a date column: To_Date stores monotonic ISO-8601 strings,
    # so a date threshold like "2015-01-01" filters chronologically. Both ISO-date
    # strings and numbers already sort correctly on the raw column.
    col_numeric = pd.to_numeric(column, errors="coerce")
    threshold_numeric = pd.to_numeric(pd.Series([threshold]), errors="coerce").iloc[0]
    if pd.notna(threshold_numeric) and col_numeric.notna().mean() >= 0.8:
        mask = col_numeric >= threshold_numeric
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            mask = pd.to_datetime(column, errors="coerce") >= pd.to_datetime(threshold)

    filtered_df = df[mask.fillna(False)]
    filtered_df = filtered_df.sort_values(by=target_score_column, ascending=False)
    
    filtered_df.to_csv(output_csv, index=False)
    print(f"Search complete! Extracted {len(filtered_df)} target items into a brand new file: '{output_csv}'")

if __name__ == "__main__":
    numerical_filter(
        source_csv="Space_Biology",
        output_csv="Highly_Favorable_Cache",
        target_score_column="hybrid_favorability",
        threshold=0.75
    )