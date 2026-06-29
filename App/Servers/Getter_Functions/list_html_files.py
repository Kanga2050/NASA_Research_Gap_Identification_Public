import os

def list_html_files(html_dir: str) -> str:
    """Returns a list of all currently generated HTML app files."""
    catalog_info = ["# HTML Visualizations Catalog\n"]
    
    # 1. Explicitly check if the directory exists
    if not os.path.exists(html_dir):
        return f"Error: HTML directory '{html_dir}' not found."

    # 2. Use os.listdir instead of glob for consistent behavior
    files = [f for f in os.listdir(html_dir) if f.endswith(".html")]
    
    if not files:
        return "No HTML apps generated yet."
        
    # 3. Add dynamic file data (like size) to ensure the payload changes
    for file in files:
        path = os.path.join(html_dir, file)
        try:
            size_kb = os.path.getsize(path) / 1024
            catalog_info.append(f"- **{file}** ({size_kb:.2f} KB)")
        except Exception as e:
            catalog_info.append(f"- **{file}** (Error reading file: {str(e)})")

    return "\n".join(catalog_info)

if __name__ == "__main__":
    result = list_html_files(
        html_dir="App/Frontend/HTML"
    )
    print(result)