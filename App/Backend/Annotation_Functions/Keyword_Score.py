import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

def keyword_score(csv_name: str, query: str, text_column: str, new_column_name: str = "keyword_score"):

    csv_path = f"App/Backend/CSVs/{csv_name}.csv"
    print(f"Running keyword search for: '{query}'...")
    df = pd.read_csv(csv_path)
    
    corpus = df[text_column].fillna("").tolist()
    
    vectorizer = TfidfVectorizer(stop_words='english')
    tfidf_matrix = vectorizer.fit_transform(corpus)
    query_vector = vectorizer.transform([query])
    
    scores = cosine_similarity(query_vector, tfidf_matrix).flatten()
    
    df[new_column_name] = scores
    df.to_csv(csv_path, index=False)
    print(f"Success! Keyword favorability saved to column '{new_column_name}'.")

if __name__ == "__main__":

    TARGET_NAME = "Space_Biology"

    keyword_score(
        csv_name=TARGET_NAME,
        query="microgravity",
        text_column="abstract",
        new_column_name="keyword_favorability"
    )