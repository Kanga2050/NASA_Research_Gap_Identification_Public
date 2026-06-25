import pandas as pd
import numpy as np
import umap
import ast
import os

def reduce_embeddings_with_umap(
    csv_path: str, 
    embedding_column: str, 
    new_column_name: str, 
    n_components: int = 2,
    metric: str = 'cosine'
):
    """
    Reads a CSV, applies UMAP to reduce the dimensionality of an embedding column,
    and saves the results to a new column in-place.
    
    Parameters:
    - csv_path: Path to the CSV file.
    - embedding_column: Name of the column containing stringified embeddings.
    - new_column_name: Name for the new column holding the UMAP coordinates.
    - n_components: The target number of dimensions (2 is standard for 2D plots).
    - metric: Distance metric. 'cosine' is best for text embeddings.
    """
    
    print(f"Loading data from '{csv_path}'...")
    df = pd.read_csv(csv_path)
    
    if embedding_column not in df.columns:
        raise ValueError(f"Column '{embedding_column}' not found in the CSV.")

    print("Parsing embeddings from strings to numerical arrays...")
    # CSVs store arrays as strings. ast.literal_eval safely parses them back to Python lists.
    # We use dropna() to avoid errors on rows that might be missing embeddings.
    valid_rows = df[embedding_column].dropna().index
    
    parsed_embeddings = df.loc[valid_rows, embedding_column].apply(ast.literal_eval)
    
    # Convert the series of lists into a 2D numpy array required by UMAP
    X = np.vstack(parsed_embeddings.values)
    
    print(f"Applying UMAP (reducing to {n_components} dimensions using '{metric}' metric)...")
    print("This may take a few minutes depending on dataset size.")
    
    # Initialize and fit UMAP
    reducer = umap.UMAP(n_components=n_components, metric=metric, n_neighbors=15, min_dist=0.1, random_state=42)
    reduced_embeddings = reducer.fit_transform(X)
    
    print("Saving reduced embeddings back to the dataframe...")
    
    # Create an empty column first to handle potential missing values cleanly
    df[new_column_name] = None
    
    df.loc[valid_rows, new_column_name] = pd.Series(reduced_embeddings.tolist(), index=valid_rows)
    
    print(f"Writing updated dataset safely to '{csv_path}'...")
    temp_path = csv_path + ".tmp"
    df.to_csv(temp_path, index=False)
    
    # Safely replace the old file with the new one
    os.replace(temp_path, csv_path)
    
    print(f"Success! Dimensionality reduction complete. Column '{new_column_name}' added.")

# ==========================================
# Example Usage
# ==========================================
if __name__ == "__main__":
    
    TARGET_FILE = "App/Backend/CSVs/Space_Biology.csv"
    
    reduce_embeddings_with_umap(
        csv_path=TARGET_FILE,
        embedding_column="abstract_embedding",
        new_column_name="5d",
        n_components=5,      # 5 is perfect for 5D visualization
        metric='cosine'      # ALWAYS use cosine for text vectors (SentenceTransformers)
    )