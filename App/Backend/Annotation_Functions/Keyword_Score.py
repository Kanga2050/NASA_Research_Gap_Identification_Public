from pathlib import Path

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from Backend.backend_utils import atomic_write_csv
from Servers.storage_paths import resolve_csv_path

def keyword_score(csv_name: str, query: str, text_column: str, new_column_name: str = "keyword_score", csv_root: str | Path | None = None):

    csv_path = resolve_csv_path(csv_name, csv_root)
    print(f"Running keyword search for: '{query}'...")
    df = pd.read_csv(csv_path)

    corpus = df[text_column].fillna("").tolist()

    # TF-IDF vectors are sparse; keep sklearn's cosine_similarity (works directly on
    # sparse matrices) rather than densifying for a hand-rolled numpy version.
    vectorizer = TfidfVectorizer(stop_words='english')
    tfidf_matrix = vectorizer.fit_transform(corpus)
    query_vector = vectorizer.transform([query])

    scores = cosine_similarity(query_vector, tfidf_matrix).flatten()

    df[new_column_name] = scores
    atomic_write_csv(df, csv_path)
    print(f"Success! Keyword favorability saved to column '{new_column_name}'.")

if __name__ == "__main__":

    TARGET_NAME = "Space_Biology"

    keyword_score(
        csv_name=TARGET_NAME,
        query="microgravity",
        text_column="abstract",
        new_column_name="keyword_favorability"
    )