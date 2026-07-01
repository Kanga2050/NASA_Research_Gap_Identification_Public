from pathlib import Path

from django.conf import settings


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_storage_root(user) -> Path:
    return ensure_directory(settings.DATA_ROOT / f"user_{user.id}")


def user_csv_root(user) -> Path:
    return ensure_directory(user_storage_root(user) / "csvs")


def user_html_root(user) -> Path:
    return ensure_directory(user_storage_root(user) / "html")


def user_task_root(user) -> Path:
    return ensure_directory(user_storage_root(user) / "tasks")