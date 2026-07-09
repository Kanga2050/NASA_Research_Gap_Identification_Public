from pathlib import Path

import pandas as pd
import plotly.express as px

from Servers.storage_paths import resolve_csv_path, resolve_html_path


def histogram(
    csv_name: str,
    value_column: str,
    bins: int = 30,
    title: str = "",
    output_name: str = "histogram",
    color_column: str = "",
    log_x: bool = False,
    log_y: bool = False,
    csv_root: str | Path | None = None,
    html_root: str | Path | None = None,
):
    """Render the distribution of a numeric column as a histogram (e.g. the spread
    of favorability scores). Pass `color_column` to overlay one series per category
    (e.g. by source); `log_x`/`log_y` switch that axis to a logarithmic scale, which
    is handy when counts span several orders of magnitude."""
    csv_path = resolve_csv_path(csv_name, csv_root)
    output_html = resolve_html_path(output_name, html_root)

    print(f"Loading data from '{csv_path}'...")
    df = pd.read_csv(csv_path)
    if value_column not in df.columns:
        raise ValueError(f"Column '{value_column}' was not found in the CSV.")

    df[value_column] = pd.to_numeric(df[value_column], errors="coerce")
    color = color_column or None
    if color:
        if color not in df.columns:
            raise ValueError(f"Column '{color}' was not found in the CSV.")
        df[color] = df[color].astype(str)

    fig = px.histogram(
        df, x=value_column, color=color, nbins=int(bins),
        log_x=bool(log_x), log_y=bool(log_y),
        title=title or f"Distribution of {value_column}",
        barmode="overlay",
    )
    if color:
        fig.update_traces(opacity=0.7)
    fig.write_html(output_html)
    print(f"Success! Histogram saved to {output_html}")


if __name__ == "__main__":
    histogram(
        csv_name="Space_Biology",
        value_column="hybrid_favorability",
        output_name="Favorability_Histogram",
        log_y=True,
    )
