import os
import pandas as pd

def get_csv_catalog(data_dir: str) -> str:
    """
    Returns a list of all CSVs in the data folder, their exact column names, 
    and their approximate size in rows and megabytes.
    """
    catalog_info = ["# CSV Data Catalog\n"]
    
    if not os.path.exists(data_dir):
        return f"Error: Data directory '{data_dir}' not found."

    for file in os.listdir(data_dir):
        if file.endswith(".csv"):
            path = os.path.join(data_dir, file)
            size_mb = os.path.getsize(path) / (1024 * 1024)
            
            try:
                df_header = pd.read_csv(path, nrows=0)
                columns = list(df_header.columns)
                
                with open(path, 'rb') as f:
                    row_count = sum(1 for _ in f) - 1 
                
                catalog_info.append(f"### {file}")
                catalog_info.append(f"- **Size:** {size_mb:.2f} MB ({row_count} rows)")
                catalog_info.append(f"- **Columns:** {', '.join(columns)}\n")
            except Exception as e:
                catalog_info.append(f"### {file}\n- **Error reading file:** {str(e)}\n")

    return "\n".join(catalog_info)

if __name__ == "__main__":
    result = get_csv_catalog(
        data_dir="App/Backend/CSVs"
    )
    print(result)