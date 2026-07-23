from pathlib import Path

import pandas as pd

from Servers.storage_paths import resolve_csv_root

def get_csv_catalog(storage_root: str | Path | None = None) -> str:
    """
    Returns a list of all CSVs in the data folder, their exact column names, 
    and their approximate size in rows and megabytes.
    """
    data_dir = Path(resolve_csv_root(storage_root))
    catalog_info = ["# CSV Data Catalog\n"]

    # CSVs live in real subfolders now (Corpora/, Derived/, ...), so this has to walk
    # the tree rather than list the root -- a non-recursive listdir would silently
    # drop every foldered file from the catalog.
    for path in sorted(data_dir.rglob("*.csv")):
        file = path.name
        size_mb = path.stat().st_size / (1024 * 1024)

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
    result = get_csv_catalog()
    print(result)