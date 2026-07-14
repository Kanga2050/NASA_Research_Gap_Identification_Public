from pathlib import Path

import pandas as pd
import numpy as np
import hdbscan
import ast

from Backend.backend_utils import atomic_write_csv
from Servers.storage_paths import resolve_csv_path

def cluster(
    csv_name: str, 
    embedding_column: str, 
    new_column_name: str = None, 
    min_cluster_size: int = 50,
    min_samples: int = 10,
    csv_root: str | Path | None = None,
):
    """
    Reads a CSV, applies HDBSCAN clustering to a column of embeddings (like UMAP 2D coordinates),
    and assigns topic labels to each row.
    
    Parameters:
    - csv_path: Path to the CSV file.
    - embedding_column: Column containing the stringified arrays (e.g., '[0.5, 1.2]').
    - new_column_name: Name for the new topic column. Defaults to '{embedding_column}_topic'.
    - min_cluster_size: The minimum number of documents required to form a valid topic.
    - min_samples: Controls how conservative the clustering is (higher = more noise).
    """
    
    csv_path = resolve_csv_path(csv_name, csv_root)
    if new_column_name is None:
        new_column_name = f"{embedding_column}_topic"
        
    print(f"Loading '{csv_name}.csv' to cluster coordinates in column '{embedding_column}'...")
    df = pd.read_csv(csv_path)

    if embedding_column not in df.columns:
        raise ValueError(f"Column '{embedding_column}' not found in the CSV.")

    valid_rows = df[embedding_column].dropna().index
    print(f"Parsing {len(valid_rows):,} coordinate vectors from '{embedding_column}'...")
    parsed_embeddings = df.loc[valid_rows, embedding_column].apply(ast.literal_eval)

    X = np.vstack(parsed_embeddings.values)

    print(f"Running HDBSCAN on {X.shape[0]:,} points (min_cluster_size={min_cluster_size}, min_samples={min_samples})...")
    print("Density clustering runs as one pass with no incremental progress; please wait...")
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric='euclidean'
    )

    cluster_labels = clusterer.fit_predict(X)

    n_topics = len(set(cluster_labels)) - (1 if -1 in cluster_labels else 0)
    n_noise = int((cluster_labels == -1).sum())
    print(f"Found {n_topics} distinct topics; {n_noise:,} points ({n_noise / len(cluster_labels) * 100:.1f}%) fell into noise (-1).")

    df[new_column_name] = None

    df.loc[valid_rows, new_column_name] = cluster_labels

    atomic_write_csv(df, csv_path)

    print(f"Success! Assigned {n_topics} topic ids to column '{new_column_name}' in '{csv_name}.csv' (label -1 = noise, not a topic).")

if __name__ == "__main__":
    
    TARGET_NAME = "Space_Biology"
    
    cluster(
        csv_name=TARGET_NAME,
        embedding_column="5d",  
        new_column_name="topic_id",
        min_cluster_size=32,
        min_samples=8 
    )