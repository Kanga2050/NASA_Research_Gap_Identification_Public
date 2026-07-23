from pathlib import Path

from Servers.storage_paths import resolve_html_root

def list_html_files(storage_root: str | Path | None = None) -> str:
    """Returns a list of all currently generated HTML app files."""

    html_dir = Path(resolve_html_root(storage_root))
    catalog_info = ["# HTML Visualizations Catalog\n"]

    # Charts live in real subfolders now (Figures/, Extras/, ...), so this has to
    # walk the tree -- a non-recursive listdir would silently drop every foldered file.
    files = sorted(html_dir.rglob("*.html"))

    if not files:
        return "No HTML apps generated yet."

    for path in files:
        file = path.name
        try:
            size_kb = path.stat().st_size / 1024
            catalog_info.append(f"- **{file}** ({size_kb:.2f} KB)")
        except Exception as e:
            catalog_info.append(f"- **{file}** (Error reading file: {str(e)})")

    return "\n".join(catalog_info)

if __name__ == "__main__":
    result = list_html_files()
    print(result)