from pathlib import Path

import pandas as pd
import numpy as np
import ast
from sentence_transformers import SentenceTransformer

from Backend.backend_utils import atomic_write_csv, cosine_similarity_dense
from Servers.storage_paths import resolve_csv_path

def semantic_score(csv_name: str, query: str, embedding_column: str, new_column_name: str = "semantic_score", model_name: str = 'allenai/specter2_base', csv_root: str | Path | None = None):
    csv_path = resolve_csv_path(csv_name, csv_root)
    print(f"Loading '{csv_name}.csv' to semantic-score embeddings in column '{embedding_column}' against query '{query}'...")
    df = pd.read_csv(csv_path)

    print(f"Loading model '{model_name}' and embedding the query '{query}'...")
    model = SentenceTransformer(model_name)
    query_embedding = model.encode([query])

    valid_rows = df[embedding_column].dropna().index
    print(f"Parsing {len(valid_rows):,} stored embeddings and computing cosine similarity to the query...")
    parsed_embeddings = df.loc[valid_rows, embedding_column].apply(ast.literal_eval)
    X = np.vstack(parsed_embeddings.values)

    scores = cosine_similarity_dense(query_embedding, X).flatten()

    df[new_column_name] = 0.0
    df.loc[valid_rows, new_column_name] = scores

    atomic_write_csv(df, csv_path)
    print(f"Success! Semantic (meaning-based) relevance to '{query}' saved to column '{new_column_name}' for {len(valid_rows):,} rows.")

if __name__ == "__main__":

    TARGET_NAME = "Space_Biology"
    semantic_score(
        csv_name=TARGET_NAME,
        query="radiation shielding mars regolith",
        embedding_column="abstract_embedding",
        new_column_name="semantic_favorability"
    )