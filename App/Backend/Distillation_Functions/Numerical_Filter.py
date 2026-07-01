import pandas as pd

def numerical_filter(source_csv: str, output_csv: str, target_score_column: str, threshold: float):
    source_csv = f"App/Backend/CSVs/{source_csv}.csv"
    output_csv = f"App/Backend/CSVs/{output_csv}.csv"

    print(f"Filtering dataset on '{target_score_column}' with a minimum threshold of {threshold}...")
    df = pd.read_csv(source_csv)
    
    if target_score_column not in df.columns:
        raise ValueError(f"Score column '{target_score_column}' was not found in the source dataset.")
        
    # Extract only rows clearing your hard metric requirement
    filtered_df = df[df[target_score_column] >= threshold]
    
    # Sort descending so the most favorable papers sit cleanly at the top of your new file
    filtered_df = filtered_df.sort_values(by=target_score_column, ascending=False)
    
    filtered_df.to_csv(output_csv, index=False)
    print(f"Search complete! Extracted {len(filtered_df)} target items into a brand new file: '{output_csv}'")

if __name__ == "__main__":
    numerical_filter(
        source_csv="Space_Biology",
        output_csv="Highly_Favorable_Cache",
        target_score_column="hybrid_favorability",
        threshold=0.75  # Extracts entries matching the top tier of your hybrid search 
    )