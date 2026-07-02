from __future__ import annotations

import pandas as pd

from App.Frontend.webapp.storage import user_csv_root, user_html_root
from .output_preview import resolve_safe_path


def list_user_csv_names(user) -> list[str]:
    return sorted(p.stem for p in user_csv_root(user).glob("*.csv"))


def list_user_html_names(user) -> list[str]:
    return sorted(p.stem for p in user_html_root(user).glob("*.html"))


def list_csv_columns(user, csv_name: str) -> list[str]:
    csv_path = resolve_safe_path(user_csv_root(user), csv_name, ".csv")
    if csv_path is None or not csv_path.exists():
        return []
    return list(pd.read_csv(csv_path, nrows=0).columns)
