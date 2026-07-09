from pathlib import Path

import pandas as pd
import numpy as np
import umap
import ast

from Backend.backend_utils import atomic_write_csv
from Servers.storage_paths import resolve_csv_path

def reduce_dimensionality(
    csv_name: str, 
    embedding_column: str, 
    new_column_name: str, 
    n_components: int = 2,
    metric: str = 'cosine',
    csv_root: str | Path | None = None,
):
    """
    Reads a CSV, applies UMAP to reduce the dimensionality of an embedding column,
    and saves the results to a new column in-place.
    
    Parameters:
    - csv_name: Name of the CSV file (without path or extension).
    - embedding_column: Name of the column containing stringified embeddings.
    - new_column_name: Name for the new column holding the UMAP coordinates.
    - n_components: The target number of dimensions (2 is standard for 2D plots).
    - metric: Distance metric. 'cosine' is best for text embeddings.
    """
    
    csv_path = resolve_csv_path(csv_name, csv_root)
    print(f"Loading data from '{csv_path}'...")
    df = pd.read_csv(csv_path)
    
    if embedding_column not in df.columns:
        raise ValueError(f"Column '{embedding_column}' not found in the CSV.")

    print("Parsing embeddings from strings to numerical arrays...")
    valid_rows = df[embedding_column].dropna().index
    
    parsed_embeddings = df.loc[valid_rows, embedding_column].apply(ast.literal_eval)
    
    X = np.vstack(parsed_embeddings.values)
    
    print(f"Applying UMAP (reducing to {n_components} dimensions using '{metric}' metric)...")
    print("This may take a few minutes depending on dataset size.")
    
    reducer = umap.UMAP(n_components=n_components, metric=metric, n_neighbors=15, min_dist=0.1, random_state=42)
    reduced_embeddings = reducer.fit_transform(X)
    
    print("Saving reduced embeddings back to the dataframe...")
    
    df[new_column_name] = None
    
    df.loc[valid_rows, new_column_name] = pd.Series(reduced_embeddings.tolist(), index=valid_rows)

    print(f"Writing updated dataset safely to '{csv_path}'...")
    atomic_write_csv(df, csv_path)

    print(f"Success! Dimensionality reduction complete. Column '{new_column_name}' added.")

if __name__ == "__main__":
    
    TARGET_NAME = "Space_Biology"
    
    reduce_dimensionality(
        csv_path=TARGET_NAME,
        embedding_column="abstract_embedding",
        new_column_name="5d",
        n_components=5,
        metric='cosine'
    )