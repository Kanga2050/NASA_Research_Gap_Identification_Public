import os
import pandas as pd

def get_csv_segment(data_dir: str, filename: str, start_row: int, num_rows: int, columns: str) -> str:
    """
    Retrieves a specific segment of a CSV.
    - data_dir: The directory containing the target csv file
    - filename: The name of the csv file (e.g., 'data.csv')
    - start_row: The index of the first row to read (0-indexed)
    - num_rows: How many rows to return
    - columns: Comma-separated list of columns, or 'all' for all columns
    """
    path = os.path.join(data_dir, filename)
    
    if not os.path.exists(path):
        return f"Error: File '{filename}' not found at '{path}'."

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
        data_dir="App/Backend/CSVs",
        filename="Space_Biology.csv",
        start_row=0,
        num_rows=10,
        columns="all"
    )
    print(segment_data)