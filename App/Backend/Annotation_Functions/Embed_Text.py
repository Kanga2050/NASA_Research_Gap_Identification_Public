from pathlib import Path

import pandas as pd
from sentence_transformers import SentenceTransformer
import os

from Backend.backend_utils import ProgressReporter
from Servers.storage_paths import resolve_csv_path

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
    csv_path = resolve_csv_path(csv_name, csv_root)
    print(f"Loading embedding model '{model_name}' (first run downloads weights, this can take ~30s)...")
    model = SentenceTransformer(model_name)
    print(f"Model ready. Streaming '{csv_name}.csv' in chunks of {chunk_size:,} rows to embed column '{text_column}'.")

    temp_csv_path = Path(f"{csv_path}.tmp")

    if os.path.exists(temp_csv_path):
        os.remove(temp_csv_path)

    first_chunk = True
    rows_done = 0

    for chunk_index, chunk in enumerate(pd.read_csv(csv_path, chunksize=chunk_size)):
        if text_column not in chunk.columns:
            os.remove(temp_csv_path)
            raise ValueError(f"Column '{text_column}' not found in the CSV.")
        texts = chunk[text_column].fillna("").astype(str).tolist()

        # Encode batch-by-batch (rather than one big call) so the progress bar can
        # advance within the chunk -- model.encode's own bar goes to stderr and
        # never reaches the frontend.
        reporter = ProgressReporter(f"Embedding rows (chunk {chunk_index + 1})", len(texts))
        embeddings = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            embeddings.extend(model.encode(batch, batch_size=batch_size, show_progress_bar=False).tolist())
            reporter.update(start + len(batch))

        chunk[new_column_name] = embeddings

        mode = 'w' if first_chunk else 'a'
        header = first_chunk

        chunk.to_csv(temp_csv_path, mode=mode, header=header, index=False)
        first_chunk = False
        rows_done += len(texts)
        print(f"Chunk {chunk_index + 1} embedded and buffered ({rows_done:,} rows done so far).")

    print("Committing embeddings to disk (atomic replace)...")
    os.replace(temp_csv_path, csv_path)
    print(f"Success! Embedded {rows_done:,} rows of '{text_column}' into new column '{new_column_name}' in '{csv_name}.csv'.")

if __name__ == "__main__":
    
    TARGET_NAME = "Space_Biology"
    
    embed_text(
        csv_name=TARGET_NAME,
        text_column="abstract",
        new_column_name="abstract_embedding",
        model_name='allenai/specter2_base'
    )