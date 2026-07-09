from pathlib import Path

import pandas as pd

from Backend.backend_utils import drop_excluded
from Servers.storage_paths import resolve_csv_path

ALLOWED_AGGS = {"count", "mean", "sum", "min", "max"}


def group_aggregate(source_csv: str, output_csv: str, group_column: str, value_column: str = "", agg: str = "count", exclude: str = "", csv_root: str | Path | None = None):
    """Group rows by `group_column` and aggregate them into a summary CSV. Pass a
    comma-separated `group_column` (e.g. "Topic_Label,year") to group by several
    columns at once, producing long-form multi-dimensional counts. With agg="count"
    (or no `value_column`) it counts rows per group; otherwise it applies
    mean/sum/min/max to `value_column`. `exclude` drops comma-separated values of the
    first group column before aggregating (e.g. "-1" to omit the HDBSCAN noise
    cluster). Result is sorted by the aggregate descending."""
    source_path = resolve_csv_path(source_csv, csv_root)
    output_path = resolve_csv_path(output_csv, csv_root)

    agg = (agg or "count").lower()
    if agg not in ALLOWED_AGGS:
        raise ValueError(f"Unsupported aggregation '{agg}'. Choose one of {sorted(ALLOWED_AGGS)}.")

    group_cols = [col.strip() for col in str(group_column).split(",") if col.strip()]
    print(f"Grouping '{source_csv}' by {group_cols} ({agg})...")
    df = pd.read_csv(source_path)

    missing = [col for col in group_cols if col not in df.columns]
    if missing:
        raise ValueError(f"Group column(s) {missing} were not found in the source dataset.")

    df = drop_excluded(df, group_cols[0], exclude)

    if agg == "count" or not value_column:
        result = df.groupby(group_cols, dropna=False).size().reset_index(name="count")
        result_column = "count"
    else:
        if value_column not in df.columns:
            raise ValueError(f"Value column '{value_column}' was not found in the source dataset.")
        result_column = f"{value_column}_{agg}"
        result = df.groupby(group_cols, dropna=False)[value_column].agg(agg).reset_index(name=result_column)

    result = result.sort_values(by=result_column, ascending=False)
    result.to_csv(output_path, index=False)
    print(f"Success! Wrote {len(result)} groups into '{output_csv}'.")


if __name__ == "__main__":
    group_aggregate(
        source_csv="Space_Biology",
        output_csv="Topic_Frequencies",
        group_column="topic_id",
        agg="count",
    )
