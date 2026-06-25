import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

def keyword_search(csv_path: str, query: str, text_column: str, new_column_name: str = "keyword_score"):
    print(f"Running keyword search for: '{query}'...")
    df = pd.read_csv(csv_path)
    
    # Handle missing text values safely
    corpus = df[text_column].fillna("").tolist()
    
    # Vectorize the text data and the incoming search query
    vectorizer = TfidfVectorizer(stop_words='english')
    tfidf_matrix = vectorizer.fit_transform(corpus)
    query_vector = vectorizer.transform([query])
    
    # Calculate lexical cosine similarity
    scores = cosine_similarity(query_vector, tfidf_matrix).flatten()
    
    # Save the favorability metrics back to the CSV
    df[new_column_name] = scores
    df.to_csv(csv_path, index=False)
    print(f"Success! Keyword favorability saved to column '{new_column_name}'.")

if __name__ == "__main__":
    keyword_search(
        csv_path="App/Backend/CSVs/Space_Biology.csv",
        query="microgravity",
        text_column="abstract",
        new_column_name="keyword_favorability"
    )