import os

def list_html_files() -> str:
    """Returns a list of all currently generated HTML app files."""

    html_dir = "./App/Backend/Visualizations"
    catalog_info = ["# HTML Visualizations Catalog\n"]
    

    files = [f for f in os.listdir(html_dir) if f.endswith(".html")]
    
    if not files:
        return "No HTML apps generated yet."
        
    for file in files:
        path = os.path.join(html_dir, file)
        try:
            size_kb = os.path.getsize(path) / 1024
            catalog_info.append(f"- **{file}** ({size_kb:.2f} KB)")
        except Exception as e:
            catalog_info.append(f"- **{file}** (Error reading file: {str(e)})")

    return "\n".join(catalog_info)

if __name__ == "__main__":
    result = list_html_files()
    print(result)