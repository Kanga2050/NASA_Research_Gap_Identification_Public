from pathlib import Path

import pandas as pd
import plotly.express as px

from Servers.storage_paths import resolve_csv_path, resolve_html_path


def heatmap(
    csv_name: str,
    x_column: str,
    y_column: str,
    value_column: str = "",
    title: str = "",
    output_name: str = "heatmap",
    csv_root: str | Path | None = None,
    html_root: str | Path | None = None,
):
    """Render a 2D heatmap. With no `value_column` it shows the count density of
    (x, y) pairs; with one, it pivots to show the mean of `value_column` for each
    (x, y) cell."""
    csv_path = resolve_csv_path(csv_name, csv_root)
    output_html = resolve_html_path(output_name, html_root)

    print(f"Loading data from '{csv_path}'...")
    df = pd.read_csv(csv_path)
    for column in (x_column, y_column):
        if column not in df.columns:
            raise ValueError(f"Column '{column}' was not found in the CSV.")

    if value_column:
        if value_column not in df.columns:
            raise ValueError(f"Value column '{value_column}' was not found in the CSV.")
        pivot = df.pivot_table(index=y_column, columns=x_column, values=value_column, aggfunc="mean")
        fig = px.imshow(
            pivot, aspect="auto", text_auto=False,
            title=title or f"Mean {value_column} by {x_column} and {y_column}",
            labels={"x": x_column, "y": y_column, "color": value_column},
        )
    else:
        fig = px.density_heatmap(
            df, x=x_column, y=y_column,
            title=title or f"Density of {x_column} vs {y_column}",
        )
    fig.write_html(output_html)
    print(f"Success! Heatmap saved to {output_html}")


if __name__ == "__main__":
    heatmap(
        csv_name="Space_Biology",
        x_column="topic_id",
        y_column="year",
        output_name="Topic_Year_Heatmap",
    )
