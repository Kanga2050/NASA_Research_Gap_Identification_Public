from pathlib import Path

import pandas as pd
from sentence_transformers import SentenceTransformer
import os

def embed_text(
    csv_name: str, 
    text_column: str, 
    new_column_name: str, 
    model_name: str = 'all-MiniLM-L6-v2',
    chunk_size: int = 5000, 
    batch_size: int = 32,
    csv_root: str | Path | None = None,
):
    """
    Reads a CSV, generates text embeddings for a specific column, 
    and updates the CSV in-place with the new column.
    """
    csv_path = Path(csv_root) / f"{csv_name}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{csv_name}.csv")
    print(f"Loading model '{model_name}'...")
    model = SentenceTransformer(model_name)
    
    temp_csv_path = Path(f"{csv_path}.tmp")
    
    if os.path.exists(temp_csv_path):
        os.remove(temp_csv_path)

    print(f"Processing '{csv_path}' in chunks of {chunk_size}...")
    
    first_chunk = True
    
    for chunk_index, chunk in enumerate(pd.read_csv(csv_path, chunksize=chunk_size)):
        print(f"Processing chunk {chunk_index + 1}...")
        
        if text_column not in chunk.columns:
            os.remove(temp_csv_path)
            raise ValueError(f"Column '{text_column}' not found in the CSV.")
        texts = chunk[text_column].fillna("").astype(str).tolist()

        embeddings = model.encode(texts, batch_size=batch_size, show_progress_bar=True)

        chunk[new_column_name] = embeddings.tolist()

        mode = 'w' if first_chunk else 'a'
        header = first_chunk
        
        chunk.to_csv(temp_csv_path, mode=mode, header=header, index=False)
        first_chunk = False

    print("Finalizing file replacement...")
    os.replace(temp_csv_path, csv_path)
    print(f"Success! '{csv_path}' has been updated with the '{new_column_name}' column.")

if __name__ == "__main__":
    
    TARGET_NAME = "Space_Biology"
    
    embed_text(
        csv_name=TARGET_NAME,
        text_column="abstract",
        new_column_name="abstract_embedding",
        model_name='allenai/specter2_base'
    )