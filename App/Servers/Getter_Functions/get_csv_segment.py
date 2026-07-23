from pathlib import Path

import os
import pandas as pd

from Servers.storage_paths import resolve_csv_path

def get_csv_segment(csv_name: str, start_row: int, num_rows: int, columns: str, storage_root: str | Path | None = None) -> str:
    """
    Retrieves a specific segment of a CSV.
    - filename: The name of the csv file (e.g., 'data.csv')
    - start_row: The index of the first row to read (0-indexed)
    - num_rows: How many rows to return
    - columns: Comma-separated list of columns, or 'all' for all columns
    """
    # CSVs live in real subfolders now, so a bare name is resolved by searching the
    # tree (same lookup the rest of the app uses), not just the root itself.
    path = resolve_csv_path(csv_name, storage_root)

    if not os.path.exists(path):
        return f"Error: File '{csv_name}' not found at '{path}'."

    usecols = None 
    if columns.lower() != "all":
        usecols = [col.strip() for col in columns.split(",")]

    try:
        df = pd.read_csv(
            path,
            skiprows=range(1, start_row + 1),
            nrows=num_rows,
            usecols=usecols
        )
        
        if df.empty:
            return "No data found at this row segment (End of file reached)."

        for col in df.columns:
            if df[col].dtype == object: # usually strings
                df[col] = df[col].astype(str).apply(
                    lambda x: x[:30] + "... [truncated]" if len(x) > 30 else x
                )

        return df.to_markdown(index=False)
        
    except ValueError as e:
        return f"Column Error: Make sure the columns requested exist. Details: {str(e)}"
    except Exception as e:
        return f"Error reading segment: {str(e)}"

if __name__ == "__main__":
    segment_data = get_csv_segment(
        csv_name="Space_Biology",
        start_row=0,
        num_rows=10,
        columns="all"
    )
    print(segment_data)