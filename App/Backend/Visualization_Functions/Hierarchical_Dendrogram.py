import ast
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.figure_factory as ff
from scipy.cluster.hierarchy import linkage

from Backend.backend_utils import ProgressReporter
from Backend.nlp_utils import top_keywords
from Servers.storage_paths import resolve_csv_path, resolve_html_path


def _parse_vector(value) -> np.ndarray:
    return np.asarray(ast.literal_eval(value), dtype=float)


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
    """Render an HTML dendrogram of a corpus's topics. Each topic is reduced to the
    mean of its members' `embedding_column` vectors (a centroid), the centroids are
    joined bottom-up with Ward hierarchical clustering, and the resulting tree shows
    which topics fuse into broader "super-themes" and how far apart the branches sit.
    Keeps the `top_n` largest topics (by document count) so the tree stays legible;
    each leaf is labelled with the topic's top keywords and its size. The HDBSCAN
    noise cluster (-1) is excluded."""
    csv_path = resolve_csv_path(csv_name, csv_root)
    output_html = resolve_html_path(output_name, html_root)

    print(f"Loading '{csv_name}.csv' to build a topic dendrogram from '{embedding_column}'...")
    df = pd.read_csv(csv_path, usecols=lambda c: c in {topic_column, text_column, embedding_column})
    for column in (topic_column, text_column, embedding_column):
        if column not in df.columns:
            raise ValueError(f"Column '{column}' was not found in the CSV.")

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
        vectors = np.vstack(members[embedding_column].apply(_parse_vector).values)
        centroids.append(vectors.mean(axis=0))
        keywords = top_keywords(members[text_column].fillna("").tolist(), 3)
        labels.append(f"{keywords}  (n={len(members):,})")
        reporter.update(i)

    matrix = np.vstack(centroids)
    print(f"Linking {len(labels)} topic centroids with Ward hierarchical clustering...")
    fig = ff.create_dendrogram(
        matrix,
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

    fig.write_html(output_html)
    print(f"Success! Dendrogram of {len(labels)} topics saved to '{output_name}.html'.")


if __name__ == "__main__":
    hierarchical_dendrogram(
        csv_name="Space_Biology",
        topic_column="topic_id",
        text_column="text",
        embedding_column="5d",
        output_name="Space_Biology_Dendrogram",
        top_n=30,
    )
