from pathlib import Path


def default_csv_root() -> Path:
    return Path("./App/Backend/CSVs")


def default_html_root() -> Path:
    return Path("./App/Backend/Visualizations")


def default_template_root() -> Path:
    return Path("./App/Backend/Templates")


def resolve_csv_root(storage_root: str | Path | None = None) -> Path:
    if storage_root is None:
        return default_csv_root()
    return Path(storage_root)


def resolve_html_root(storage_root: str | Path | None = None) -> Path:
    if storage_root is None:
        return default_html_root()
    return Path(storage_root)