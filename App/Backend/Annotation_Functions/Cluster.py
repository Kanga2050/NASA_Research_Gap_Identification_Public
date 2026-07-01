import pandas as pd
import numpy as np
import hdbscan
import ast
import os

def cluster(
    csv_name: str, 
    embedding_column: str, 
    new_column_name: str = None, 
    min_cluster_size: int = 50,
    min_samples: int = 10
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
    
    csv_path = f"App/Backend/CSVs/{csv_name}.csv"
    # If no new column name is provided, default to appending '_topic'
    if new_column_name is None:
        new_column_name = f"{embedding_column}_topic"
        
    print(f"Loading data from '{csv_path}'...")
    df = pd.read_csv(csv_path)
    
    if embedding_column not in df.columns:
        raise ValueError(f"Column '{embedding_column}' not found in the CSV.")

    print(f"Parsing coordinates from '{embedding_column}'...")
    # Drop NaNs to avoid parsing errors on empty rows
    valid_rows = df[embedding_column].dropna().index
    parsed_embeddings = df.loc[valid_rows, embedding_column].apply(ast.literal_eval)
    
    # Convert lists to a 2D numpy array
    X = np.vstack(parsed_embeddings.values)
    
    print(f"Running HDBSCAN clustering (min_cluster_size={min_cluster_size})...")
    # Initialize and fit the HDBSCAN model
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size, 
        min_samples=min_samples,
        metric='euclidean' # Euclidean is correct here if running on UMAP 2D coordinates
    )
    
    # Generate labels. HDBSCAN outputs integers (0, 1, 2...) for clusters, and -1 for noise.
    cluster_labels = clusterer.fit_predict(X)
    
    print(f"Found {len(set(cluster_labels)) - (1 if -1 in cluster_labels else 0)} distinct topics.")
    
    # Create the new column with empty values initially
    df[new_column_name] = None
    
    # Assign the labels back to the dataframe
    df.loc[valid_rows, new_column_name] = cluster_labels
    
    print(f"Writing updated dataset safely to '{csv_path}'...")
    temp_path = csv_path + ".tmp"
    df.to_csv(temp_path, index=False)
    
    # Safely replace the old file
    os.replace(temp_path, csv_path)
    
    print(f"Success! Topic labels added to column '{new_column_name}'.")
    print("Note: A label of '-1' means the entry is 'noise' and doesn't fit into a dense topic.")

# ==========================================
# Example Usage
# ==========================================
if __name__ == "__main__":
    
    TARGET_NAME = "Space_Biology"
    
    cluster(
        csv_name=TARGET_NAME,
        embedding_column="5d",  
        new_column_name="topic_id",
        min_cluster_size=32,
        min_samples=8 
    )