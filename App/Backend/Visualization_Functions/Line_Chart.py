from pathlib import Path

import pandas as pd
import plotly.express as px

from Servers.storage_paths import resolve_csv_path, resolve_html_path


def line_chart(
    csv_name: str,
    x_column: str,
    y_column: str,
    color_column: str = "",
    title: str = "",
    output_name: str = "line_chart",
    csv_root: str | Path | None = None,
    html_root: str | Path | None = None,
):
    """Render a line chart of `y_column` against `x_column`, sorted by x (e.g. paper
    counts per year). Pass `color_column` to draw one line per category. Pre-
    aggregate with `group_aggregate` when you want one point per x value."""
    csv_path = resolve_csv_path(csv_name, csv_root)
    output_html = resolve_html_path(output_name, html_root)

    print(f"Loading data from '{csv_path}'...")
    df = pd.read_csv(csv_path)
    for column in (x_column, y_column):
        if column not in df.columns:
            raise ValueError(f"Column '{column}' was not found in the CSV.")

    color = color_column or None
    data = df.sort_values(by=x_column)

    fig = px.line(
        data, x=x_column, y=y_column, color=color,
        title=title or f"{y_column} over {x_column}",
        markers=True,
    )
    fig.write_html(output_html)
    print(f"Success! Line chart saved to {output_html}")


if __name__ == "__main__":
    line_chart(
        csv_name="Papers_Per_Year",
        x_column="year",
        y_column="count",
        output_name="Papers_Per_Year_Line",
    )
