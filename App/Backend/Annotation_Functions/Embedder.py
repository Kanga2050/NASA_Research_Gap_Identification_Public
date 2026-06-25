import pandas as pd
from sentence_transformers import SentenceTransformer
import os

def add_embeddings_in_place(
    csv_path: str, 
    text_column: str, 
    new_column_name: str, 
    model_name: str = 'all-MiniLM-L6-v2',
    chunk_size: int = 5000, 
    batch_size: int = 32
):
    """
    Reads a CSV, generates text embeddings for a specific column, 
    and updates the CSV in-place with the new column.
    """
    
    print(f"Loading model '{model_name}'...")
    model = SentenceTransformer(model_name)
    
    # Create a temporary file path to safely write data to
    temp_csv_path = csv_path + ".tmp"
    
    if os.path.exists(temp_csv_path):
        os.remove(temp_csv_path)

    print(f"Processing '{csv_path}' in chunks of {chunk_size}...")
    
    first_chunk = True
    
    # Process the CSV in chunks
    for chunk_index, chunk in enumerate(pd.read_csv(csv_path, chunksize=chunk_size)):
        print(f"Processing chunk {chunk_index + 1}...")
        
        if text_column not in chunk.columns:
            # Clean up the temp file if we hit an error
            os.remove(temp_csv_path)
            raise ValueError(f"Column '{text_column}' not found in the CSV.")

        # Extract text, handling missing values
        texts = chunk[text_column].fillna("").astype(str).tolist()

        # Generate embeddings
        embeddings = model.encode(texts, batch_size=batch_size, show_progress_bar=True)

        # Add the embeddings as a new column
        chunk[new_column_name] = embeddings.tolist()

        # Append the processed chunk to the temporary CSV
        mode = 'w' if first_chunk else 'a'
        header = first_chunk
        
        chunk.to_csv(temp_csv_path, mode=mode, header=header, index=False)
        first_chunk = False

    # Once fully successful, replace the original file with the temporary one
    print("Finalizing file replacement...")
    os.replace(temp_csv_path, csv_path)
    print(f"Success! '{csv_path}' has been updated with the '{new_column_name}' column.")

# ==========================================
# Example Usage
# ==========================================
if __name__ == "__main__":
    
    TARGET_FILE = "App/Backend/CSVs/Space_Biology.csv"
    
    add_embeddings_in_place(
        csv_path=TARGET_FILE,
        text_column="abstract",
        new_column_name="abstract_embedding",
        model_name='allenai/specter2_base'
    )