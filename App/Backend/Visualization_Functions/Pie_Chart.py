from pathlib import Path

import pandas as pd
import plotly.express as px

from Backend.backend_utils import drop_excluded
from Servers.storage_paths import resolve_csv_path, resolve_html_path


def pie_chart(
    csv_name: str,
    category_column: str,
    value_column: str = "",
    title: str = "",
    output_name: str = "pie_chart",
    top_n: int = 10,
    exclude: str = "",
    csv_root: str | Path | None = None,
    html_root: str | Path | None = None,
):
    """Render a pie chart of category proportions. With no `value_column` it uses
    row counts per category; with one, it sums that value per category. `top_n`
    keeps only the largest slices; `exclude` drops comma-separated category values
    first (e.g. "-1" to omit the HDBSCAN noise cluster)."""
    csv_path = resolve_csv_path(csv_name, csv_root)
    output_html = resolve_html_path(output_name, html_root)

    print(f"Loading '{csv_name}.csv' to build a pie chart of '{category_column}' shares...")
    df = pd.read_csv(csv_path)
    if category_column not in df.columns:
        raise ValueError(f"Column '{category_column}' was not found in the CSV.")

    df = drop_excluded(df, category_column, exclude)
    measure = f"summed '{value_column}'" if value_column else "row counts"
    print(f"Aggregating {len(df):,} rows into per-'{category_column}' {measure}...")
    if value_column:
        if value_column not in df.columns:
            raise ValueError(f"Value column '{value_column}' was not found in the CSV.")
        data = df.groupby(category_column, dropna=False)[value_column].sum().reset_index()
        values = value_column
    else:
        data = df.groupby(category_column, dropna=False).size().reset_index(name="count")
        values = "count"

    data[category_column] = data[category_column].astype(str)
    data = data.sort_values(values, ascending=False)
    if top_n and int(top_n) > 0:
        data = data.head(int(top_n))

    slices = len(data)
    print(f"Rendering pie chart of {slices} slices...")
    fig = px.pie(
        data, names=category_column, values=values,
        title=title or f"{values} share by {category_column}",
    )
    fig.write_html(output_html)
    print(f"Success! Pie chart of {slices} slices saved to '{output_name}.html'.")


if __name__ == "__main__":
    pie_chart(
        csv_name="Space_Biology",
        category_column="topic_id",
        output_name="Topic_Share_Pie",
    )
