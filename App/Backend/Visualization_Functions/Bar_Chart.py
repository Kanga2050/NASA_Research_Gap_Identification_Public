from pathlib import Path

import pandas as pd
import plotly.express as px

from Backend.backend_utils import drop_excluded
from Servers.storage_paths import resolve_csv_path, resolve_html_path


def bar_chart(
    csv_name: str,
    category_column: str,
    value_column: str = "",
    series_column: str = "",
    title: str = "",
    output_name: str = "bar_chart",
    top_n: int = 25,
    exclude: str = "",
    csv_root: str | Path | None = None,
    html_root: str | Path | None = None,
):
    """Render a bar chart to HTML. With no `value_column` it counts the frequency of
    each `category_column` value; with one, it sums that value per category. Provide
    `series_column` to split each bar into grouped sub-bars (e.g. counts per source).
    `top_n` keeps only the largest categories; `exclude` drops comma-separated
    category values first (e.g. "-1" to omit the HDBSCAN noise cluster)."""
    csv_path = resolve_csv_path(csv_name, csv_root)
    output_html = resolve_html_path(output_name, html_root)

    print(f"Loading data from '{csv_path}'...")
    df = pd.read_csv(csv_path)
    if category_column not in df.columns:
        raise ValueError(f"Column '{category_column}' was not found in the CSV.")

    df = drop_excluded(df, category_column, exclude)
    series = series_column or None
    group_cols = [category_column] + ([series] if series else [])

    if value_column:
        if value_column not in df.columns:
            raise ValueError(f"Value column '{value_column}' was not found in the CSV.")
        data = df.groupby(group_cols, dropna=False)[value_column].sum().reset_index()
        y_column = value_column
    else:
        data = df.groupby(group_cols, dropna=False).size().reset_index(name="count")
        y_column = "count"

    # Keep only the top_n categories by total height.
    if top_n and int(top_n) > 0:
        totals = data.groupby(category_column)[y_column].sum().sort_values(ascending=False)
        data = data[data[category_column].isin(totals.head(int(top_n)).index)]

    data[category_column] = data[category_column].astype(str)
    if series:
        data[series] = data[series].astype(str)
    data = data.sort_values(y_column, ascending=False)

    fig = px.bar(
        data, x=category_column, y=y_column, color=series,
        title=title or f"{y_column} by {category_column}",
        barmode="group",
    )
    fig.update_layout(xaxis={"categoryorder": "total descending"})
    fig.write_html(output_html)
    print(f"Success! Bar chart saved to {output_html}")


if __name__ == "__main__":
    bar_chart(
        csv_name="Space_Biology",
        category_column="topic_id",
        output_name="Topic_Frequency_Bar",
        title="Topic frequency",
    )
