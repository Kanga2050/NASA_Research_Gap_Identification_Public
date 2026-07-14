from pathlib import Path

import pandas as pd
import plotly.express as px

from Backend.backend_utils import drop_excluded
from Servers.storage_paths import resolve_csv_path, resolve_html_path


def box_plot(
    csv_name: str,
    value_column: str,
    category_column: str = "",
    title: str = "",
    output_name: str = "box_plot",
    exclude: str = "",
    log_y: bool = False,
    csv_root: str | Path | None = None,
    html_root: str | Path | None = None,
):
    """Render a box plot of `value_column`'s distribution. Pass `category_column` to
    draw one box per category (e.g. favorability spread per topic). `exclude` drops
    comma-separated category values first; `log_y` uses a logarithmic y-axis."""
    csv_path = resolve_csv_path(csv_name, csv_root)
    output_html = resolve_html_path(output_name, html_root)

    print(f"Loading '{csv_name}.csv' to build a box plot of '{value_column}'...")
    df = pd.read_csv(csv_path)
    if value_column not in df.columns:
        raise ValueError(f"Column '{value_column}' was not found in the CSV.")

    df[value_column] = pd.to_numeric(df[value_column], errors="coerce")
    category = category_column or None
    if category:
        if category not in df.columns:
            raise ValueError(f"Column '{category}' was not found in the CSV.")
        df = drop_excluded(df, category, exclude)
        df[category] = df[category].astype(str)

    boxes = df[category].nunique() if category else 1
    split = f"one box per '{category}' ({boxes} boxes)" if category else "a single box"
    print(f"Rendering box plot of {len(df):,} values as {split}" + (" (log-y)" if log_y else "") + "...")
    fig = px.box(
        df, x=category, y=value_column, log_y=bool(log_y),
        title=title or (f"{value_column} by {category}" if category else f"Distribution of {value_column}"),
    )
    fig.write_html(output_html)
    print(f"Success! Box plot ({boxes} box(es), {len(df):,} values) saved to '{output_name}.html'.")


if __name__ == "__main__":
    box_plot(
        csv_name="Space_Biology",
        value_column="hybrid_favorability",
        category_column="topic_id",
        output_name="Favorability_By_Topic_Box",
    )
