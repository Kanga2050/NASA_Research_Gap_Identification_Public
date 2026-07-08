import ast
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px

from Servers.storage_paths import resolve_csv_root, resolve_html_root


def scatter_plot(
    csv_name: str,
    x_column: str = "",
    y_column: str = "",
    color_column: str = "",
    size_column: str = "",
    coord_column: str = "",
    title: str = "",
    output_name: str = "scatter_plot",
    csv_root: str | Path | None = None,
    html_root: str | Path | None = None,
):
    """Render a 2D scatter plot to HTML. Either pass two numeric columns
    (`x_column`, `y_column`) or a single `coord_column` holding stringified "[x, y]"
    pairs (like the "2d" UMAP column) which is unpacked into axes. `color_column`
    tints points by category; `size_column` scales them (bubble chart)."""
    csv_path = resolve_csv_root(csv_root) / f"{csv_name}.csv"
    output_html = resolve_html_root(html_root) / f"{output_name}.html"

    print(f"Loading data from '{csv_path}'...")
    df = pd.read_csv(csv_path)

    if coord_column:
        if coord_column not in df.columns:
            raise ValueError(f"Coordinate column '{coord_column}' was not found in the CSV.")
        valid = df[coord_column].dropna().index
        parsed = df.loc[valid, coord_column].apply(ast.literal_eval)
        df["x"] = np.nan
        df["y"] = np.nan
        df.loc[valid, "x"] = [coord[0] for coord in parsed]
        df.loc[valid, "y"] = [coord[1] for coord in parsed]
        x_axis, y_axis = "x", "y"
    else:
        if not x_column or not y_column:
            raise ValueError("Provide both x_column and y_column, or a coord_column.")
        for column in (x_column, y_column):
            if column not in df.columns:
                raise ValueError(f"Column '{column}' was not found in the CSV.")
        x_axis, y_axis = x_column, y_column

    color = color_column or None
    if color:
        df[color] = df[color].astype(str)  # categorical coloring, not a gradient
    size = size_column or None
    if size:
        df[size] = pd.to_numeric(df[size], errors="coerce").clip(lower=0)

    fig = px.scatter(
        df, x=x_axis, y=y_axis, color=color, size=size,
        title=title or f"{y_axis} vs {x_axis}",
        opacity=0.7,
    )
    fig.write_html(output_html)
    print(f"Success! Scatter plot saved to {output_html}")


if __name__ == "__main__":
    scatter_plot(
        csv_name="Space_Biology",
        coord_column="2d",
        color_column="topic_id",
        output_name="Embedding_Scatter",
        title="Document embedding map",
    )
