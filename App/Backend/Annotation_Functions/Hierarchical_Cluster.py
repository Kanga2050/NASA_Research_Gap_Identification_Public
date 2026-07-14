import ast
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist

from Backend.backend_utils import ProgressReporter, atomic_write_csv
from Servers.storage_paths import resolve_csv_path


def _parse_vector(value) -> np.ndarray:
    return np.asarray(ast.literal_eval(value), dtype=float)


def hierarchical_cluster(
    csv_name: str,
    topic_column: str = "topic_id",
    embedding_column: str = "5d",
    output_column: str = "hcluster",
    n_clusters: int = 10,
    csv_root: str | Path | None = None,
):
    """Agglomerate an existing topic assignment into a smaller number of hierarchical
    "super-clusters", writing each row's super-cluster id into `output_column`. Each
    topic is reduced to the centroid of its members' `embedding_column` vectors; the
    centroids are joined with Ward linkage and the tree is cut to yield `n_clusters`
    groups, so related fine-grained topics collapse into a few broad themes. This is
    a top-down complement to HDBSCAN's flat `cluster`: same partition, coarser grain,
    and every topic lands in a theme (only noise / un-coordinated rows stay -1). Edits
    the CSV in place. Queues a background task; returns its task_id."""
    csv_path = resolve_csv_path(csv_name, csv_root)

    print(f"Loading '{csv_name}.csv' to agglomerate topics from '{topic_column}' into super-clusters...")
    df = pd.read_csv(csv_path)
    for column in (topic_column, embedding_column):
        if column not in df.columns:
            raise ValueError(f"Column '{column}' was not found in the CSV.")

    topic_num = pd.to_numeric(df[topic_column], errors="coerce")
    valid = topic_num.notna() & (topic_num != -1) & df[embedding_column].notna()
    topic_ids = sorted(topic_num[valid].astype(int).unique())
    if len(topic_ids) < 2:
        raise ValueError("Need at least two non-noise topics to agglomerate.")

    print(f"Building centroids for {len(topic_ids)} topics...")
    reporter = ProgressReporter("Building topic centroids", len(topic_ids))
    centroids = []
    for i, topic_id in enumerate(topic_ids, start=1):
        members = df[valid & (topic_num == topic_id)]
        vectors = np.vstack(members[embedding_column].apply(_parse_vector).values)
        centroids.append(vectors.mean(axis=0))
        reporter.update(i)

    matrix = np.vstack(centroids)
    k = max(2, min(int(n_clusters), len(topic_ids)))
    print(f"Ward-linking {len(topic_ids)} centroids and cutting the tree into {k} super-clusters...")
    linkage_matrix = linkage(pdist(matrix), method="ward")
    super_ids = fcluster(linkage_matrix, t=k, criterion="maxclust")
    topic_to_super = {topic_id: int(super_id) for topic_id, super_id in zip(topic_ids, super_ids)}

    mapped = topic_num.map(topic_to_super)
    df[output_column] = mapped.fillna(-1).astype(int)
    assigned = int(mapped.notna().sum())

    atomic_write_csv(df, csv_path)
    sizes = df[output_column].value_counts().drop(index=-1, errors="ignore").sort_index()
    print(f"Success! Mapped {len(topic_ids)} topics onto {k} super-clusters in '{output_column}' "
          f"({assigned:,} rows assigned). Sizes: {sizes.to_dict()}")


if __name__ == "__main__":
    hierarchical_cluster(
        csv_name="Space_Biology",
        topic_column="topic_id",
        embedding_column="5d",
        output_column="hcluster",
        n_clusters=10,
    )
