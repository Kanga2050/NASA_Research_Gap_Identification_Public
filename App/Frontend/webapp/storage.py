import re
from pathlib import Path

from django.conf import settings


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def storage_folder_name(user) -> str:
    """The single on-disk folder segment for a user, derived from their username.

    Usernames are constrained by Django's validator to ``[A-Za-z0-9@.+-_]``,
    which is filesystem-safe apart from ``.``/``..`` (which would escape or alias
    the data root). Any stray character is replaced and leading/trailing dots are
    stripped; if nothing usable remains we fall back to the stable ``user_<id>``.
    """
    raw = (user.get_username() or "").strip()
    safe = re.sub(r"[^\w.@+-]", "_", raw, flags=re.UNICODE).strip(". ")
    return safe or f"user_{user.id}"


def user_storage_root(user) -> Path:
    """Return (creating if needed) the user's storage root, keyed by username.

    Historically roots were named ``user_<id>``; if such a legacy folder is found
    and the username-named folder doesn't exist yet, it is migrated in place so
    existing data follows the user to their new folder name.
    """
    target = settings.DATA_ROOT / storage_folder_name(user)
    if not target.exists():
        legacy = settings.DATA_ROOT / f"user_{user.id}"
        if legacy.exists() and legacy != target:
            legacy.rename(target)
    return ensure_directory(target)


def rename_user_storage(old_folder_name: str, new_folder_name: str) -> None:
    """Move a user's storage folder when their username changes. Safe to call
    when nothing needs moving (missing source, unchanged name, or a name clash)."""
    if not old_folder_name or old_folder_name == new_folder_name:
        return
    old_path = settings.DATA_ROOT / old_folder_name
    new_path = settings.DATA_ROOT / new_folder_name
    if old_path.exists() and not new_path.exists():
        old_path.rename(new_path)


def user_csv_root(user) -> Path:
    return ensure_directory(user_storage_root(user) / "csvs")


def user_task_root(user) -> Path:
    return ensure_directory(user_storage_root(user) / "tasks")


def user_pdf_root(user) -> Path:
    """Per-user PDF area. Unlike csvs/html (flat files), this holds *collection*
    subfolders (`pdfs/<collection>/*.pdf`) that chunk_pdfs ingests as a unit."""
    return ensure_directory(user_storage_root(user) / "pdfs")


def user_template_root(user) -> Path:
    """Per-user folder for saved Studio graph templates (JSON files)."""
    return ensure_directory(user_storage_root(user) / "templates")


def user_paper_root(user) -> Path:
    """Per-user folder for Synthesize research papers: each paper's block-model
    ``<name>.json`` is authored/re-edited here, and sits right alongside the
    self-contained interactive ``<name>.html`` it's *built* into (see Paper_Builder),
    once it has been built."""
    return ensure_directory(user_storage_root(user) / "papers")


# --- Shared "public" library folders -----------------------------------------
# A single commons any signed-in user can publish to and pull from. CSVs already
# ship populated; Templates/Papers are created on demand. A Studio recipe's
# rendered chart, and a paper's built report, live right alongside it in
# Templates/Papers respectively -- there is no separate "Visualizations" root.
def public_csv_root() -> Path:
    return ensure_directory(settings.BASE_DIR / "App" / "Backend" / "CSVs")


def public_template_root() -> Path:
    return ensure_directory(settings.BASE_DIR / "App" / "Backend" / "Templates")


def public_paper_root() -> Path:
    """Shared library of Synthesize papers (JSON block-model docs) any signed-in
    user can pull as a starting template — e.g. the Space Biology report."""
    return ensure_directory(settings.BASE_DIR / "App" / "Backend" / "Papers")


def public_pdf_root() -> Path:
    """Shared PDF library: `App/Backend/PDFs/<collection>/*.pdf`. Any signed-in
    user can pull a collection from here into their own pdfs area."""
    return ensure_directory(settings.BASE_DIR / "App" / "Backend" / "PDFs")
