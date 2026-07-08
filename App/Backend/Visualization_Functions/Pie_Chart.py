from pathlib import Path

import pandas as pd
import plotly.express as px

from Servers.storage_paths import resolve_csv_root, resolve_html_root


def drop_excluded(df, column, exclude):
    """Drop rows whose `column` value (as text) is in the comma-separated `exclude`
    list -- e.g. "-1" to omit the HDBSCAN noise cluster from a topic chart."""
    if not exclude:
        return df
    drop = {value.strip() for value in str(exclude).split(",") if value.strip()}
    return df[~df[column].astype(str).isin(drop)]


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
    csv_path = resolve_csv_root(csv_root) / f"{csv_name}.csv"
    output_html = resolve_html_root(html_root) / f"{output_name}.html"

    print(f"Loading data from '{csv_path}'...")
    df = pd.read_csv(csv_path)
    if category_column not in df.columns:
        raise ValueError(f"Column '{category_column}' was not found in the CSV.")

    df = drop_excluded(df, category_column, exclude)
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

    fig = px.pie(
        data, names=category_column, values=values,
        title=title or f"{values} share by {category_column}",
    )
    fig.write_html(output_html)
    print(f"Success! Pie chart saved to {output_html}")


if __name__ == "__main__":
    pie_chart(
        csv_name="Space_Biology",
        category_column="topic_id",
        output_name="Topic_Share_Pie",
    )
