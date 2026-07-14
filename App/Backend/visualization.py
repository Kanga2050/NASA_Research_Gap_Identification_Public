"""Visualization functions: read a CSV and render an interactive Plotly chart to HTML.

These are terminal nodes -- they produce no new column or table, only a self-contained
`<output_name>.html` in the caller's visualizations area, which the dashboard can show,
the user can publish, and a Synthesize paper can embed as a live figure.

scipy and spaCy are imported inside the two functions that need them, so the eight
charts that don't never pay for them.
"""
from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px

from .backend_utils import (
    ProgressReporter,
    as_bool,
    count_or_sum,
    drop_excluded,
    load_csv,
    require_columns,
    stacked_vectors,
    write_chart,
)


def _unpack_coords(df: pd.DataFrame, coord_column: str) -> pd.DataFrame:
    """Explode a column of stringified "[x, y]" pairs (the 2D UMAP column) into real
    `x`/`y` columns. Rows without a coordinate are left as NaN."""
    valid = df[coord_column].dropna().index
    print(f"Unpacking {len(valid):,} '[x, y]' coordinate pairs from column '{coord_column}'...")
    parsed = df.loc[valid, coord_column].apply(ast.literal_eval)
    df["x"] = np.nan
    df["y"] = np.nan
    df.loc[valid, "x"] = [coord[0] for coord in parsed]
    df.loc[valid, "y"] = [coord[1] for coord in parsed]
    return df


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
    """Render a bar chart. With no `value_column` it counts the frequency of each
    `category_column` value; with one, it sums that value per category. `series_column`
    splits each bar into grouped sub-bars; `top_n` keeps only the largest categories;
    `exclude` drops comma-separated category values first (e.g. "-1" for noise)."""
    print(f"Loading '{csv_name}.csv' to build a bar chart of '{category_column}'...")
    df = load_csv(csv_name, csv_root, columns=(category_column, series_column))

    df = drop_excluded(df, category_column, exclude)
    series = series_column or None
    group_cols = [category_column] + ([series] if series else [])

    measure = f"summed '{value_column}'" if value_column else "row counts"
    print(f"Aggregating {len(df):,} rows into per-'{category_column}' {measure}...")
    data, y_column = count_or_sum(df, group_cols, value_column)

    # Keep only the top_n categories by total bar height.
    if top_n and int(top_n) > 0:
        totals = data.groupby(category_column)[y_column].sum().sort_values(ascending=False)
        data = data[data[category_column].isin(totals.head(int(top_n)).index)]

    data[category_column] = data[category_column].astype(str)
    if series:
        data[series] = data[series].astype(str)
    data = data.sort_values(y_column, ascending=False)

    bars = data[category_column].nunique()
    print(f"Rendering bar chart of {bars} categories" + (f" split by '{series}'" if series else "") + "...")
    fig = px.bar(
        data, x=category_column, y=y_column, color=series,
        title=title or f"{y_column} by {category_column}",
        barmode="group",
    )
    fig.update_layout(xaxis={"categoryorder": "total descending"})

    write_chart(fig, output_name, html_root, f"Bar chart of {bars} categories")


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
    """Render a pie chart of category proportions. With no `value_column` it uses row
    counts per category; with one, it sums that value per category. `top_n` keeps only
    the largest slices; `exclude` drops comma-separated category values first."""
    print(f"Loading '{csv_name}.csv' to build a pie chart of '{category_column}' shares...")
    df = load_csv(csv_name, csv_root, columns=(category_column,))

    df = drop_excluded(df, category_column, exclude)
    measure = f"summed '{value_column}'" if value_column else "row counts"
    print(f"Aggregating {len(df):,} rows into per-'{category_column}' {measure}...")
    data, values = count_or_sum(df, [category_column], value_column)

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

    write_chart(fig, output_name, html_root, f"Pie chart of {slices} slices")


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
    """Render the distribution of a numeric column as a histogram. Pass `color_column`
    to overlay one series per category; `log_x`/`log_y` switch that axis to a
    logarithmic scale, which helps when counts span orders of magnitude."""
    print(f"Loading '{csv_name}.csv' to build a histogram of '{value_column}'...")
    df = load_csv(csv_name, csv_root, columns=(value_column, color_column))

    df[value_column] = pd.to_numeric(df[value_column], errors="coerce")
    color = color_column or None
    if color:
        df[color] = df[color].astype(str)

    bins, log_x, log_y = int(bins), as_bool(log_x), as_bool(log_y)
    valid = int(df[value_column].notna().sum())
    axes = (" (log-x)" if log_x else "") + (" (log-y)" if log_y else "")
    print(f"Binning {valid:,} values of '{value_column}' into {bins} bins"
          + (f", overlaid by '{color}'" if color else "") + axes + "...")
    fig = px.histogram(
        df, x=value_column, color=color, nbins=bins,
        log_x=log_x, log_y=log_y,
        title=title or f"Distribution of {value_column}",
        barmode="overlay",
    )
    if color:
        fig.update_traces(opacity=0.7)

    write_chart(fig, output_name, html_root, f"Histogram of {valid:,} values ({bins} bins)")


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
    counts per year). Pass `color_column` to draw one line per category. Pre-aggregate
    with `group_aggregate` when you want one point per x value."""
    print(f"Loading '{csv_name}.csv' to build a line chart of '{y_column}' over '{x_column}'...")
    df = load_csv(csv_name, csv_root, columns=(x_column, y_column, color_column))

    color = color_column or None
    data = df.sort_values(by=x_column)

    lines = data[color].nunique() if color else 1
    print(f"Rendering {lines} line(s) across {len(data):,} points, sorted by '{x_column}'...")
    fig = px.line(
        data, x=x_column, y=y_column, color=color,
        title=title or f"{y_column} over {x_column}",
        markers=True,
    )

    write_chart(fig, output_name, html_root, f"Line chart ({lines} series, {len(data):,} points)")


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
    print(f"Loading '{csv_name}.csv' to build a box plot of '{value_column}'...")
    df = load_csv(csv_name, csv_root, columns=(value_column, category_column))

    df[value_column] = pd.to_numeric(df[value_column], errors="coerce")
    category = category_column or None
    if category:
        df = drop_excluded(df, category, exclude)
        df[category] = df[category].astype(str)

    log_y = as_bool(log_y)
    boxes = df[category].nunique() if category else 1
    split = f"one box per '{category}' ({boxes} boxes)" if category else "a single box"
    print(f"Rendering box plot of {len(df):,} values as {split}" + (" (log-y)" if log_y else "") + "...")
    fig = px.box(
        df, x=category, y=value_column, log_y=log_y,
        title=title or (f"{value_column} by {category}" if category else f"Distribution of {value_column}"),
    )

    write_chart(fig, output_name, html_root, f"Box plot ({boxes} box(es), {len(df):,} values)")


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
    (x, y) pairs; with one, it pivots to show the mean of `value_column` per cell."""
    mode = f"mean of '{value_column}'" if value_column else "count density"
    print(f"Loading '{csv_name}.csv' to build a heatmap ({mode}) of '{x_column}' × '{y_column}'...")
    df = load_csv(csv_name, csv_root, columns=(x_column, y_column, value_column))

    if value_column:
        print(f"Pivoting {len(df):,} rows into a '{y_column}' × '{x_column}' grid of mean '{value_column}'...")
        pivot = df.pivot_table(index=y_column, columns=x_column, values=value_column, aggfunc="mean")
        fig = px.imshow(
            pivot, aspect="auto", text_auto=False,
            title=title or f"Mean {value_column} by {x_column} and {y_column}",
            labels={"x": x_column, "y": y_column, "color": value_column},
        )
    else:
        print(f"Binning {len(df):,} rows into a '{x_column}' × '{y_column}' density grid...")
        fig = px.density_heatmap(
            df, x=x_column, y=y_column,
            title=title or f"Density of {x_column} vs {y_column}",
        )

    write_chart(fig, output_name, html_root, f"Heatmap ({mode}) of '{x_column}' × '{y_column}'")


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
    """Render a 2D scatter plot. Either pass two numeric columns (`x_column`,
    `y_column`) or a single `coord_column` holding stringified "[x, y]" pairs (like the
    "2d" UMAP column), which is unpacked into axes. `color_column` tints points by
    category; `size_column` scales them into a bubble chart."""
    print(f"Loading '{csv_name}.csv' to build a scatter plot...")
    df = load_csv(csv_name, csv_root, columns=(color_column, size_column))

    if coord_column:
        require_columns(df, coord_column)
        df = _unpack_coords(df, coord_column)
        x_axis, y_axis = "x", "y"
    else:
        if not x_column or not y_column:
            raise ValueError("Provide both x_column and y_column, or a coord_column.")
        require_columns(df, x_column, y_column)
        x_axis, y_axis = x_column, y_column

    color = color_column or None
    if color:
        df[color] = df[color].astype(str)  # categorical coloring, not a gradient
    size = size_column or None
    if size:
        df[size] = pd.to_numeric(df[size], errors="coerce").clip(lower=0)

    print(f"Rendering scatter plot of {len(df):,} points ({x_axis} vs {y_axis}"
          + (f", coloured by '{color}'" if color else "") + ")...")
    fig = px.scatter(
        df, x=x_axis, y=y_axis, color=color, size=size,
        title=title or f"{y_axis} vs {x_axis}",
        opacity=0.7,
    )

    write_chart(fig, output_name, html_root, f"Scatter plot of {len(df):,} points")


def distance_map(
    csv_name: str,
    topic_column: str,
    text_column: str = "text",
    coord_column: str = "2d",
    output_name: str = "Space_Biology_Topics",
    title: str = "",
    csv_root: str | Path | None = None,
    html_root: str | Path | None = None,
):
    """Render an intertopic distance map: one bubble per topic, positioned at its mean
    2D coordinate, sized by document count and labelled with its top keywords. The
    HDBSCAN noise cluster (-1) is excluded."""
    from .nlp_utils import top_keywords

    print(f"Loading '{csv_name}.csv' to build an intertopic distance map from '{topic_column}'...")
    df = load_csv(csv_name, csv_root, columns=(topic_column, text_column, coord_column))

    df = _unpack_coords(df, coord_column)
    topics_df = df[df[topic_column] != -1]

    stats = topics_df.groupby(topic_column).agg(
        x=("x", "mean"), y=("y", "mean"), size=("x", "count")
    ).reset_index()

    topic_ids = list(stats[topic_column])
    reporter = ProgressReporter(f"Labelling {len(topic_ids)} topics (top 3 keywords each)", len(topic_ids))
    labels = {}
    for i, topic_id in enumerate(topic_ids, start=1):
        texts = topics_df.loc[topics_df[topic_column] == topic_id, text_column].fillna("").tolist()
        labels[topic_id] = top_keywords(texts, 3)
        reporter.update(i)
    stats["Topic_Label"] = stats[topic_column].map(labels)

    print(f"Rendering {len(stats)} topic bubbles (size = document count)...")
    fig = px.scatter(
        stats, x="x", y="y", size="size",
        color="Topic_Label", hover_name="Topic_Label",
        title=title or "Intertopic Distance Map",
        size_max=60,
    )
    fig.update_traces(marker=dict(sizemode="area", sizemin=5, opacity=0.8, line=dict(width=1, color="Black")))
    fig.update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False), plot_bgcolor="white")

    write_chart(fig, output_name, html_root, f"Intertopic distance map of {len(stats)} topics")


def hierarchical_dendrogram(
    csv_name: str,
    topic_column: str = "topic_id",
    text_column: str = "text",
    embedding_column: str = "5d",
    output_name: str = "Topic_Dendrogram",
    title: str = "",
    top_n: int = 30,
    orientation: str = "left",
    csv_root: str | Path | None = None,
    html_root: str | Path | None = None,
):
    """Render a dendrogram of a corpus's topics. Each topic is reduced to the mean of
    its members' `embedding_column` vectors (a centroid), the centroids are joined
    bottom-up with Ward hierarchical clustering, and the resulting tree shows which
    topics fuse into broader super-themes and how far apart the branches sit. Keeps the
    `top_n` largest topics so the tree stays legible; each leaf is labelled with the
    topic's top keywords and size. The HDBSCAN noise cluster (-1) is excluded."""
    import plotly.figure_factory as ff
    from scipy.cluster.hierarchy import linkage

    from .nlp_utils import top_keywords

    print(f"Loading '{csv_name}.csv' to build a topic dendrogram from '{embedding_column}'...")
    wanted = {topic_column, text_column, embedding_column}
    df = load_csv(csv_name, csv_root, columns=(topic_column, text_column, embedding_column),
                  usecols=lambda c: c in wanted)

    topic_num = pd.to_numeric(df[topic_column], errors="coerce")
    valid = topic_num.notna() & (topic_num != -1) & df[embedding_column].notna()
    df = df[valid].copy()
    df["_topic"] = topic_num[valid].astype(int)
    if df.empty:
        raise ValueError("No non-noise rows with coordinates were found to cluster.")

    sizes = df["_topic"].value_counts()
    keep = list(sizes.head(int(top_n)).index)
    df = df[df["_topic"].isin(keep)]
    print(f"Computing centroids for the {len(keep)} largest of {len(sizes)} topics...")

    reporter = ProgressReporter("Building topic centroids", len(keep))
    centroids, labels = [], []
    for i, topic_id in enumerate(keep, start=1):
        members = df[df["_topic"] == topic_id]
        centroids.append(stacked_vectors(members[embedding_column]).mean(axis=0))
        keywords = top_keywords(members[text_column].fillna("").tolist(), 3)
        labels.append(f"{keywords}  (n={len(members):,})")
        reporter.update(i)

    print(f"Linking {len(labels)} topic centroids with Ward hierarchical clustering...")
    fig = ff.create_dendrogram(
        np.vstack(centroids),
        orientation=orientation,
        labels=labels,
        linkagefun=lambda distances: linkage(distances, method="ward"),
    )

    horizontal = orientation in ("left", "right")
    label_room = 24 * max((len(text) for text in labels), default=20)
    fig.update_layout(
        title=title or f"Hierarchical Topic Dendrogram — {csv_name}",
        width=1150,
        height=max(600, 26 * len(labels) + 220) if horizontal else 760,
        margin=dict(
            l=min(520, label_room) if orientation == "left" else 60,
            r=min(520, label_room) if orientation == "right" else 60,
            t=90,
            b=200 if not horizontal else 90,
        ),
        plot_bgcolor="white",
        font=dict(size=12),
    )
    if horizontal:
        fig.update_xaxes(title_text="Ward linkage distance (topic dissimilarity)")
    else:
        fig.update_yaxes(title_text="Ward linkage distance (topic dissimilarity)")

    write_chart(fig, output_name, html_root, f"Dendrogram of {len(labels)} topics")
