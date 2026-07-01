import pandas as pd
import numpy as np
import ast
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

def semantic_score(csv_name: str, query: str, embedding_column: str, new_column_name: str = "semantic_score", model_name: str = 'allenai/specter2_base'):
    print(f"Running semantic search for: '{query}'...")

    csv_path = f"App/Backend/CSVs/{csv_name}.csv"
    df = pd.read_csv(csv_path)
    
    # Generate an embedding for the single query string
    model = SentenceTransformer(model_name)
    query_embedding = model.encode([query])
    
    # Safely parse existing document embeddings from strings to numerical arrays
    valid_rows = df[embedding_column].dropna().index
    parsed_embeddings = df.loc[valid_rows, embedding_column].apply(ast.literal_eval)
    X = np.vstack(parsed_embeddings.values)
    
    # Calculate semantic vector similarity
    scores = cosine_similarity(query_embedding, X).flatten()
    
    # Realign scores back to the original dataframe shape handling any NaNs safely
    df[new_column_name] = 0.0
    df.loc[valid_rows, new_column_name] = scores
    
    df.to_csv(csv_path, index=False)
    print(f"Success! Semantic favorability saved to column '{new_column_name}'.")

if __name__ == "__main__":

    TARGET_NAME = "Space_Biology"
    semantic_score(
        csv_name=TARGET_NAME,
        query="radiation shielding mars regolith",
        embedding_column="abstract_embedding",
        new_column_name="semantic_favorability"
    )