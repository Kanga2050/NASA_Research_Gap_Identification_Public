from pathlib import Path

import pandas as pd

def hybrid_score(csv_name: str, keyword_col: str, semantic_col: str, new_column_name: str = "hybrid_score", k: int = 60, csv_root: str | Path | None = None):
    print("Running Hybrid Reciprocal Rank Fusion (RRF)...")

    csv_path = Path(csv_root) / f"{csv_name}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{csv_name}.csv")
    df = pd.read_csv(csv_path)
    
    keyword_rank = df[keyword_col].rank(ascending=False, method='min')
    semantic_rank = df[semantic_col].rank(ascending=False, method='min')
    
    rrf_score = (1.0 / (k + keyword_rank)) + (1.0 / (k + semantic_rank))
    
    df[new_column_name] = (rrf_score - rrf_score.min()) / (rrf_score.max() - rrf_score.min())
    
    df.to_csv(csv_path, index=False)
    print(f"Success! Hybrid RRF favorability saved to column '{new_column_name}'.")

if __name__ == "__main__":

    TARGET_NAME = "Space_Biology"

    hybrid_score(
        csv_name=TARGET_NAME,
        keyword_col="keyword_favorability",
        semantic_col="semantic_favorability",
        new_column_name="hybrid_favorability"
    )