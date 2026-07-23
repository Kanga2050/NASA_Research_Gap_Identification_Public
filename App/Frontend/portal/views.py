import json
import os
import re
import shutil
from pathlib import Path

from django.contrib import messages
from django.contrib.auth import login as auth_login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from .agent import AgentError, genai_installed, run_agent_turn
from .data_lookups import (
    KIND_SUFFIX,
    PUBLIC_ROOTS,
    TREE_SUFFIXES,
    USER_ROOTS,
    list_csv_columns_typed,
    list_public,
    list_public_pdf_folders,
    list_public_tree,
    list_user_csv_names,
    list_user_files,
    list_user_html_names,
    list_user_paper_names,
    list_user_pdf_folders,
    list_user_tree,
    pdf_folder_choices,
    public_folder_paths,
    user_folder_paths,
)
from . import folders
from .file_meta import (DESCRIPTIONS_FILE, find_description, get_description,
                        remove_description, set_description, store_description)
from .forms import (
    AgentSettingsForm,
    ApiKeyCreateForm,
    ExternalApiSettingsForm,
    SignupForm,
    TaskSubmitForm,
    UsernameForm,
)
from .graph_manifest import MANIFEST, PALETTE
from .models import AgentSettings, ApiKey, ExternalApiSettings, TaskRecord
from .output_preview import build_named_preview, build_output_preview, get_latest_task, resolve_safe_path
from .paper_ops import safe_name
from .services import create_api_key, resolve_api_key
from . import block_ops, studio_ops
from .studio_ops import StudioError, queue_graph
from .task_engine import get_task_history, get_task_status, queue_user_task
from .user_secrets import secret_kwargs
from App.Backend import registry
from App.Frontend.webapp.storage import (
    public_pdf_root,
    rename_user_storage,
    storage_folder_name,
    user_csv_root,
    user_paper_root,
    user_pdf_root,
    user_template_root,
)
from App.Servers.Paper_Builder import build_paper_html
from App.Servers.storage_paths import resolve_html_path

# Keep the persisted chat transcript bounded so the session (and each model
# request) stays small; this holds ~AGENT_HISTORY_LIMIT/2 turns.
AGENT_HISTORY_LIMIT = 30

# Form fields that select an existing column from a CSV, rather than naming a
# new one. The dashboard renders these as dropdowns populated dynamically
# (via the csv_columns endpoint) instead of free-text inputs.
COLUMN_FIELD_NAMES = [
    "text_column",
    "embedding_column",
    "topic_column",
    "keyword_col",
    "semantic_col",
    "target_score_column",
    "target_column",
    "dict_column",
    "group_column",
    "sort_column",
    "subset_column",
    "row_column",
    "column_column",
    "date_column",
]

# Everything the dashboard's task form needs to know about each action, derived from
# the registry and handed to the page as JSON: which fields to show, which of those are
# CSV-column dropdowns (so they can be repopulated when the chosen CSV changes), and
# which field -- if any -- picks the source CSV.
ACTION_SPEC = {
    fn.name: {
        "fields": list(fn.form_fields),
        "columnFields": [f for f in fn.form_fields if f in COLUMN_FIELD_NAMES],
        "csvSource": fn.source_csv_field,
    }
    for fn in registry.ALL_FUNCTIONS
}

# Maps an import/export "kind" to the per-user storage-root accessor and dotted
# suffix for that file type. Shared by import_file/export_file/publish/describe.
KIND_ROOTS = {kind: (USER_ROOTS[kind], KIND_SUFFIX[kind]) for kind in KIND_SUFFIX}

# Uploaded file extension -> import kind. Both Studio templates and Synthesize
# papers arrive as .json, so the .json kind is resolved by content (_json_kind).
# A standalone .html upload is treated as a chart (a template's rendered half) --
# built paper reports aren't really meant to be re-uploaded independently.
EXT_TO_KIND = {"csv": "csv", "html": "template", "json": "template"}


def _json_kind(raw: bytes) -> str:
    """Disambiguate the two .json kinds by content: a Synthesize paper is a block
    model (has a `blocks` list); anything else is a Studio graph template."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return "template"
    if isinstance(payload, dict) and isinstance(payload.get("blocks"), list):
        return "paper"
    return "template"


def signup(request):
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            messages.success(request, "Account created.")
            return redirect("dashboard")
    else:
        form = SignupForm()
    return render(request, "registration/signup.html", {"form": form})


def _dashboard_context(request):
    csv_names = list_user_csv_names(request.user)
    html_names = list_user_html_names(request.user)

    latest_task = get_latest_task(request.user)
    latest_output = None
    latest_task_in_progress = False
    if latest_task is not None:
        if latest_task.status == TaskRecord.Status.COMPLETED:
            latest_output = build_output_preview(latest_task, request.user)
        elif latest_task.status in (TaskRecord.Status.QUEUED, TaskRecord.Status.WORKING):
            latest_task_in_progress = True

    tasks = get_task_history(user=request.user, limit=20)
    # "Active tasks" (Studio) is just this same list filtered to queued/working, so
    # the Dashboard's "Recent tasks" and the Studio's "Active tasks" always agree.
    active_tasks = [t for t in tasks if t["status"] in ("queued", "working")]

    return {
        "api_key_form": ApiKeyCreateForm(),
        "task_form": TaskSubmitForm(),
        "csv_names": csv_names,
        "html_names": html_names,
        "template_files": list_user_files(request.user, "template"),
        # Files organised into nested folders: the Dashboard renders these trees, and
        # the folder pickers (move / publish-into / pull-into) read the path lists.
        "file_trees": {kind: list_user_tree(request.user, kind) for kind in KIND_SUFFIX},
        "user_folder_choices": {kind: user_folder_paths(request.user, kind) for kind in KIND_SUFFIX},
        "pdf_folders": list_user_pdf_folders(request.user),
        "pdf_folder_choices": pdf_folder_choices(request.user),
        "column_field_names": COLUMN_FIELD_NAMES,
        "action_spec": ACTION_SPEC,
        "tasks": tasks,
        "active_tasks": active_tasks,
        "latest_task": latest_task,
        "latest_output": latest_output,
        "latest_task_in_progress": latest_task_in_progress,
        "api_keys": request.user.api_keys.order_by("-created_at")[:20],
        "agent_ready": genai_installed(),
        "agent_has_key": _get_agent_settings(request.user).has_key,
        "agent_history": request.session.get("agent_history", []),
    }


def _studio_context(request):
    """Visual scripting canvas: nodes wired into a pipeline, queued in dependency
    order by studio_run. Ships the function manifest and CSV names to the editor."""
    return {
        "csv_names": list_user_csv_names(request.user),
        "manifest": {"nodes": MANIFEST, "palette": PALETTE},
    }


@login_required
def dashboard(request):
    context = {
        **_dashboard_context(request),
        **_studio_context(request),
        **_synthesize_context(request),
        "active_tab": "dashboard",
    }
    return render(request, "portal/workspace.html", context)


@login_required
def csv_columns(request, name):
    # `columns` (name list) stays for the dashboard form; `typed` adds inferred
    # wire types for the Studio node editor.
    typed = list_csv_columns_typed(request.user, name)
    return JsonResponse({"columns": [c["name"] for c in typed], "typed": typed})


@login_required
def task_status(request, task_id):
    return JsonResponse(get_task_status(task_id, user=request.user))


@login_required
def task_feed(request):
    """The same task list the Dashboard's "Recent tasks" renders at page load
    (newest first, up to 20). Polled by tasks_live.js, which also derives the
    Studio's "Active tasks" from this same response, so both stay in sync."""
    return JsonResponse({"tasks": get_task_history(user=request.user, limit=20)})


@login_required
def preview_output(request, kind, name):
    """JSON preview of any CSV/HTML file the signed-in user owns, for the
    center-column "view a previous output" dropdown."""
    return JsonResponse(build_named_preview(request.user, kind, name))


@login_required
@xframe_options_sameorigin
def preview_output_html(request, name):
    # An .html name is either a chart (lives with its Studio recipe) or a built
    # paper report (lives with its document) -- try both roots.
    html_path = resolve_safe_path(user_template_root(request.user), name, ".html")
    if html_path is None or not html_path.exists():
        html_path = resolve_safe_path(user_paper_root(request.user), name, ".html")
    if html_path is None or not html_path.exists():
        raise Http404("Visualization not found.")

    return HttpResponse(html_path.read_text(encoding="utf-8"), content_type="text/html")


@login_required
@require_POST
def import_file(request):
    upload = request.FILES.get("upload")
    if not upload:
        messages.error(request, "Choose a file to import.")
        return redirect("dashboard")

    filename = os.path.basename(upload.name)
    if not filename or filename in {".", ".."} or filename == DESCRIPTIONS_FILE:
        messages.error(request, "Invalid file name.")
        return redirect("dashboard")

    ext = Path(filename).suffix.lower().lstrip(".")
    kind = EXT_TO_KIND.get(ext)
    if kind is None:
        messages.error(request, "Only .csv, .html, and .json (template or paper) files can be imported.")
        return redirect("dashboard")

    # .json is ambiguous (Studio template vs Synthesize paper) -- decide by content.
    payload = None
    if ext == "json":
        payload = upload.read()
        kind = _json_kind(payload)

    root = USER_ROOTS[kind](request.user)
    try:
        dest_dir = folders.safe_dir(root, request.POST.get("folder", ""))
    except folders.FolderError:
        messages.error(request, "Invalid destination folder.")
        return redirect("dashboard")
    dest_dir.mkdir(parents=True, exist_ok=True)
    destination = dest_dir / filename
    if payload is not None:
        destination.write_bytes(payload)
    else:
        with destination.open("wb") as out:
            for chunk in upload.chunks():
                out.write(chunk)

    description = request.POST.get("description", "")
    if description.strip():
        set_description(dest_dir, Path(filename).stem, description)

    messages.success(request, f"Imported {filename}.")
    return redirect("dashboard")


@login_required
def export_file(request, kind, name):
    """Download one physical file. A "template"/"paper" row may pair a recipe/doc
    (.json) with its rendered chart/report (.html) in the same folder now, so
    ``?ext=html`` picks the rendered half instead of the kind's default suffix."""
    if kind not in KIND_ROOTS:
        raise Http404("Unknown export kind.")

    root_fn, default_suffix = KIND_ROOTS[kind]
    requested_ext = request.GET.get("ext", "").lstrip(".")
    suffix = f".{requested_ext}" if requested_ext else default_suffix
    if suffix not in TREE_SUFFIXES.get(kind, (default_suffix,)):
        raise Http404("Unknown export kind.")

    file_path = resolve_safe_path(root_fn(request.user), name, suffix)
    if file_path is None or not file_path.exists():
        raise Http404("File not found.")

    return FileResponse(file_path.open("rb"), as_attachment=True, filename=f"{name}{suffix}")


def _unique_destination(folder: Path, name: str, suffix: str):
    """A non-clobbering destination path in `folder` for `name+suffix`, appending
    `_2`, `_3`, ... on collision. Returns (path, final_stem)."""
    candidate = folder / f"{name}{suffix}"
    if not candidate.exists():
        return candidate, name
    index = 2
    while True:
        stem = f"{name}_{index}"
        alt = folder / f"{stem}{suffix}"
        if not alt.exists():
            return alt, stem
        index += 1


def _copy_file_between(src_root: Path, dst_root: Path, kind: str, name: str, dest_folder: str):
    """Copy file(s) named ``name`` of ``kind`` from one library into ``dest_folder`` of
    another, carrying its description into the destination folder's sidecar. A
    "template"/"paper" row may pair a recipe/doc with its rendered chart/report in
    the same folder -- every sibling that exists travels together, under one shared
    stem. Returns the destination stem, or None if nothing was found."""
    suffixes = []
    for s in TREE_SUFFIXES.get(kind, (KIND_SUFFIX[kind],)):
        p = resolve_safe_path(src_root, name, s)
        if p is not None and p.exists():
            suffixes.append(s)
    if not suffixes:
        return None
    dst_dir = folders.safe_dir(dst_root, dest_folder)
    dst_dir.mkdir(parents=True, exist_ok=True)
    first_src = resolve_safe_path(src_root, name, suffixes[0])
    description = get_description(first_src.parent, first_src.stem)
    final_stem = None
    for suffix in suffixes:
        src = resolve_safe_path(src_root, name, suffix)
        if final_stem is None:
            dst, final_stem = _unique_destination(dst_dir, Path(name).name, suffix)
        else:
            dst = dst_dir / f"{final_stem}{suffix}"
        shutil.copy2(src, dst)
    if description:
        set_description(dst_dir, final_stem, description)
    return final_stem


def _copy_folder_between(src_root: Path, dst_root: Path, path: str, dest_folder: str):
    """Copy a whole folder subtree (with its per-folder sidecars) from one library into
    ``dest_folder`` of another. Returns the destination folder name, or None if missing."""
    src_dir = folders.safe_dir(src_root, path)
    if src_dir == Path(src_root).resolve() or not src_dir.is_dir():
        return None
    dst_parent = folders.safe_dir(dst_root, dest_folder)
    dst_parent.mkdir(parents=True, exist_ok=True)
    dst = dst_parent / src_dir.name
    index = 2
    while dst.exists():
        dst = dst_parent / f"{src_dir.name}_{index}"
        index += 1
    shutil.copytree(src_dir, dst)
    return dst.name


def _transfer(request, *, to_public: bool):
    """Copy a file OR a whole folder between the user's storage and the public commons.

    Publishing and pulling are the same operation with the two roots swapped, so they
    share one path; only the direction and the wording differ. ``folder`` names the
    destination folder on the receiving side (the "place it where?" prompt); ``path``
    (with ``is_folder``) transfers a whole folder instead of a single file.
    """
    kind = request.POST.get("kind")
    if kind not in KIND_SUFFIX:
        messages.error(request, "Unknown file kind.")
        return redirect("dashboard")

    user_root, public_root = USER_ROOTS[kind](request.user), PUBLIC_ROOTS[kind]()
    source, destination = (user_root, public_root) if to_public else (public_root, user_root)
    verb, where = ("publish", "the public library") if to_public else ("import", "your library")
    dest_folder = request.POST.get("folder", "")
    is_folder = request.POST.get("is_folder") in ("1", "true", "on")

    try:
        if is_folder:
            result = _copy_folder_between(source, destination, request.POST.get("path", ""), dest_folder)
            noun = f"folder “{result}”"
        else:
            result = _copy_file_between(source, destination, kind, request.POST.get("name", ""), dest_folder)
            noun = f"{result}{KIND_SUFFIX[kind]}"
    except (OSError, folders.FolderError) as exc:
        messages.error(request, f"Could not {verb}: {exc}")
        return redirect("dashboard")

    if result is None:
        messages.error(request, ("Folder" if is_folder else "File") +
                        (" not found." if to_public else " not found in the public library."))
    else:
        into = f" into {dest_folder}" if dest_folder else ""
        messages.success(request, f"{verb.title()}ed {noun} to {where}{into}.")
    return redirect("dashboard")


@login_required
@require_POST
def publish_file(request):
    """Copy one of the user's files (or a whole folder) into the public commons."""
    return _transfer(request, to_public=True)


@login_required
@require_POST
def import_from_public(request):
    """Copy a chosen file (or a whole folder) from the public commons into the user's storage."""
    return _transfer(request, to_public=False)


# --- Folder management (create / rename / move / delete) ----------------------
def _kind_root(request, kind):
    return USER_ROOTS[kind](request.user) if kind in KIND_SUFFIX else None


@login_required
@require_POST
def create_folder(request):
    kind = request.POST.get("kind")
    root = _kind_root(request, kind)
    if root is None:
        messages.error(request, "Unknown file kind.")
        return redirect("dashboard")
    try:
        folders.create_folder(root, request.POST.get("parent", ""), request.POST.get("name", ""))
        messages.success(request, f"Created folder “{request.POST.get('name', '')}”.")
    except folders.FolderError as exc:
        messages.error(request, str(exc))
    return redirect("dashboard")


@login_required
@require_POST
def rename_folder(request):
    kind = request.POST.get("kind")
    root = _kind_root(request, kind)
    if root is None:
        messages.error(request, "Unknown file kind.")
        return redirect("dashboard")
    try:
        folders.rename_folder(root, request.POST.get("path", ""), request.POST.get("name", ""))
        messages.success(request, "Folder renamed.")
    except folders.FolderError as exc:
        messages.error(request, str(exc))
    return redirect("dashboard")


@login_required
@require_POST
def delete_folder(request):
    kind = request.POST.get("kind")
    root = _kind_root(request, kind)
    if root is None:
        messages.error(request, "Unknown file kind.")
        return redirect("dashboard")
    try:
        folders.delete_folder(root, request.POST.get("path", ""))
        messages.success(request, "Folder deleted.")
    except folders.FolderError as exc:
        messages.error(request, str(exc))
    return redirect("dashboard")


@login_required
@require_POST
def move_entry(request):
    """Move a file (by ``name``) or a folder (``path`` + ``is_folder``) into ``folder``."""
    kind = request.POST.get("kind")
    root = _kind_root(request, kind)
    if root is None:
        messages.error(request, "Unknown file kind.")
        return redirect("dashboard")
    dest = request.POST.get("folder", "")
    try:
        if request.POST.get("is_folder") in ("1", "true", "on"):
            folders.move_folder(root, request.POST.get("path", ""), dest)
        else:
            # A "template"/"paper" row may pair a recipe/doc with its rendered
            # chart/report in the same folder -- move every sibling together.
            folders.move_stem(root, request.POST.get("name", ""), TREE_SUFFIXES[kind], dest)
        messages.success(request, "Moved.")
    except folders.FolderError as exc:
        messages.error(request, str(exc))
    return redirect("dashboard")


@login_required
def public_list(request):
    """JSON contents of the shared public library, for the Dashboard pull UI.

    PDF collections are folders rather than files, so they are not a KIND_SUFFIX
    kind -- but they ride in this same payload (and render as one more group in the
    public library) rather than living in a library of their own.
    """
    return JsonResponse({
        **{kind: list_public(kind) for kind in KIND_SUFFIX},
        "trees": {kind: list_public_tree(kind) for kind in KIND_SUFFIX},
        "folder_choices": {kind: public_folder_paths(kind) for kind in KIND_SUFFIX},
        "pdf": list_public_pdf_folders(),
    })


@login_required
@require_POST
def describe_file(request):
    """Set/update the description on one of the user's files (found anywhere in its tree)."""
    kind = request.POST.get("kind")
    name = request.POST.get("name", "")
    if kind not in KIND_SUFFIX:
        messages.error(request, "Unknown file kind.")
        return redirect("dashboard")

    # A "template"/"paper" row may pair a recipe/doc with its rendered chart/report
    # in the same folder -- the description sidecar is keyed by stem only, so
    # whichever sibling exists resolves to the same shared entry.
    root = USER_ROOTS[kind](request.user)
    paths = [p for s in TREE_SUFFIXES[kind]
             if (p := resolve_safe_path(root, name, s)) and p.exists()]
    if not paths:
        messages.error(request, "File not found.")
        return redirect("dashboard")

    store_description(root, name, paths[0].suffix, request.POST.get("description", ""))
    messages.success(request, f"Updated description for {Path(name).name}.")
    return redirect("dashboard")


@login_required
@require_POST
def delete_file(request):
    """Permanently delete one of the user's own files (found anywhere in its tree)."""
    kind = request.POST.get("kind")
    name = request.POST.get("name", "")
    if kind not in KIND_SUFFIX:
        messages.error(request, "Unknown file kind.")
        return redirect("dashboard")

    # Delete every sibling of this stem (a template's chart, or a paper's built
    # report, travels with its recipe/doc since they share one folder row now).
    root = USER_ROOTS[kind](request.user)
    paths = [p for s in TREE_SUFFIXES[kind]
             if (p := resolve_safe_path(root, name, s)) and p.exists()]
    if not paths:
        messages.error(request, "File not found.")
        return redirect("dashboard")

    for path in paths:
        path.unlink()
    remove_description(paths[0].parent, paths[0].stem)
    messages.success(request, f"Deleted {Path(name).name}.")
    return redirect("dashboard")


# --- PDF collections (folders of PDFs uploaded/pulled for chunk_pdfs) ----------
def _safe_collection_name(raw: str) -> str:
    """A single filesystem-safe path segment for a PDF collection folder, or ''."""
    name = os.path.basename((raw or "").strip().rstrip("/\\"))
    name = re.sub(r"[^\w.@+-]", "_", name).strip(". ")
    return "" if name in {"", ".", ".."} else name


@login_required
def pdf_folders(request):
    """JSON list of the user's PDF collections and the shared public ones.

    The dashboard renders both from page context now (its own collections in the file
    library, the public ones in the public library), so this endpoint stands purely as
    the JSON view of the same data for out-of-page callers."""
    return JsonResponse({
        "user": list_user_pdf_folders(request.user),
        "public": list_public_pdf_folders(),
    })


def _copy_pdf_collection(src_root: Path, dst_root: Path, name: str) -> str | None:
    """Copy a whole PDF collection between two PDF areas, carrying its description
    and never clobbering an existing folder (appends `_2`, `_3`, ...). Returns the
    destination folder name, or None if the source collection does not exist."""
    source = src_root / name
    if not name or not source.is_dir():
        return None

    destination = dst_root / name
    index = 2
    while destination.exists():
        destination = dst_root / f"{name}_{index}"
        index += 1

    shutil.copytree(source, destination)
    description = get_description(src_root, name)
    if description:
        set_description(dst_root, destination.name, description)
    return destination.name


@login_required
@require_POST
def describe_pdf_folder(request):
    """Set/update the description on one of the user's PDF collections."""
    collection = _safe_collection_name(request.POST.get("name", ""))
    root = user_pdf_root(request.user)
    if not collection or not (root / collection).is_dir():
        messages.error(request, "Collection not found.")
        return redirect("dashboard")

    set_description(root, collection, request.POST.get("description", ""))
    messages.success(request, f"Updated description for {collection}.")
    return redirect("dashboard")


@login_required
@require_POST
def publish_pdf_folder(request):
    """Copy one of the user's PDF collections into the shared public library."""
    collection = _safe_collection_name(request.POST.get("name", ""))
    try:
        published = _copy_pdf_collection(user_pdf_root(request.user), public_pdf_root(), collection)
    except OSError as exc:
        messages.error(request, f"Could not publish: {exc}")
        return redirect("dashboard")

    if published is None:
        messages.error(request, "Collection not found.")
    else:
        messages.success(request, f"Published PDF collection '{published}' to the public library.")
    return redirect("dashboard")


@login_required
@require_POST
def upload_pdfs(request):
    """Upload one or more PDFs into a named collection folder in the user's PDF area."""
    collection = _safe_collection_name(request.POST.get("collection", ""))
    if not collection:
        messages.error(request, "Provide a valid collection name.")
        return redirect("dashboard")

    uploads = request.FILES.getlist("pdfs")
    if not uploads:
        messages.error(request, "Choose at least one PDF to upload.")
        return redirect("dashboard")

    pdf_root = user_pdf_root(request.user)
    destination = pdf_root / collection
    destination.mkdir(parents=True, exist_ok=True)
    saved = 0
    for upload in uploads:
        safe_name = os.path.basename(upload.name)
        if not safe_name.lower().endswith(".pdf"):
            continue
        with (destination / safe_name).open("wb") as out:
            for chunk in upload.chunks():
                out.write(chunk)
        saved += 1

    if not saved:
        messages.error(request, "No PDF files were uploaded (only .pdf is accepted).")
        return redirect("dashboard")

    description = request.POST.get("description", "")
    if description.strip():
        set_description(pdf_root, collection, description)
    messages.success(request, f"Uploaded {saved} PDF(s) into collection '{collection}'.")
    return redirect("dashboard")


@login_required
@require_POST
def delete_pdf_folder(request):
    """Delete one of the user's own PDF collections."""
    collection = _safe_collection_name(request.POST.get("name", ""))
    root = user_pdf_root(request.user)
    target = root / collection
    if not collection or not target.is_dir():
        messages.error(request, "Collection not found.")
        return redirect("dashboard")
    shutil.rmtree(target)
    remove_description(root, collection)
    messages.success(request, f"Deleted PDF collection '{collection}'.")
    return redirect("dashboard")


@login_required
@require_POST
def import_pdf_folder_from_public(request):
    """Copy a public PDF collection into the user's own PDF area (non-clobbering)."""
    collection = _safe_collection_name(request.POST.get("name", ""))
    try:
        imported = _copy_pdf_collection(public_pdf_root(), user_pdf_root(request.user), collection)
    except OSError as exc:
        messages.error(request, f"Could not import: {exc}")
        return redirect("dashboard")

    if imported is None:
        messages.error(request, "Public collection not found.")
    else:
        messages.success(request, f"Imported PDF collection '{imported}' from the public library.")
    return redirect("dashboard")


@login_required
@require_POST
def issue_api_key(request):
    form = ApiKeyCreateForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Provide a valid API key name.")
        return redirect("dashboard")

    _, raw_key = create_api_key(request.user, form.cleaned_data["name"])
    request.session["last_api_key"] = raw_key
    messages.success(request, "API key created. It is shown once below.")
    return redirect("dashboard")


# A chart's .html lives right alongside the Studio recipe that made it (the
# "template" root) -- there is no longer a standalone "html" root.
ROOT_BUILDERS = {"csv": user_csv_root, "html": user_template_root, "pdf": user_pdf_root}


def _resolve_arg(cleaned: dict, param: registry.Param):
    """One positional argument for a queued task, from the submitted form data.

    A submitted value wins when it is truthy; otherwise the param's registry default
    applies. That default may be a callable taking the whole cleaned form, for the
    few defaults computed from a sibling field (e.g. a chart's output_name, which
    defaults to "<the chosen CSV>_bar_chart").
    """
    field = param.form_field
    if field and cleaned.get(field):
        return cleaned[field]
    return param.default(cleaned) if callable(param.default) else param.default


def _queue_task_for_user(user, action: str, cleaned: dict):
    """Queue any pipeline function from cleaned form data.

    The positional argument order, the storage roots and any per-user third-party keys
    come straight from the registry, so this one path serves the dashboard form, the
    Studio's Run button and the agent -- and none of them can drift out of step with
    the backend signature.
    """
    fn = registry.get(action)
    args = [_resolve_arg(cleaned, param) for param in fn.params]
    root_kwargs = {f"{name}_root": str(ROOT_BUILDERS[name](user)) for name in fn.roots}
    return queue_user_task(user, action, *args, **root_kwargs, **secret_kwargs(user, fn))


@login_required
@require_POST
def submit_task(request):
    form = TaskSubmitForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please fill in the task form correctly.")
        return redirect("dashboard")

    try:
        result = _queue_task_for_user(request.user, form.cleaned_data["action"], form.cleaned_data)
    except Exception as exc:
        messages.error(request, f"Could not queue task: {exc}")
        return redirect("dashboard")

    messages.success(request, f"Queued {form.cleaned_data['action']} as {result['task_id']}")
    return redirect("dashboard")


@login_required
def studio(request):
    context = {
        **_dashboard_context(request),
        **_studio_context(request),
        **_synthesize_context(request),
        "active_tab": "studio",
    }
    return render(request, "portal/workspace.html", context)


def _synthesize_context(request):
    """The Synthesize tab: a block editor for authoring research papers from the
    user's own charts/data. Ships the paper list plus the chart & CSV names the
    figure/reference pickers draw from."""
    return {
        "paper_files": list_user_files(request.user, "paper"),
        "paper_names": list_user_paper_names(request.user),
    }


@login_required
def synthesize(request):
    context = {
        **_dashboard_context(request),
        **_studio_context(request),
        **_synthesize_context(request),
        "active_tab": "synthesize",
    }
    return render(request, "portal/workspace.html", context)


@login_required
@require_POST
def studio_run(request):
    """Compile the canvas's node graph into queued tasks, in dependency order.

    The compiler itself lives in `studio_ops.queue_graph`, so the Run button, the
    REST API and the agent's `run_studio_pipeline` tool all queue work the same way.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid request body."}, status=400)

    try:
        queued = queue_graph(request.user, payload.get("nodes", []), payload.get("edges", []),
                             blocks=payload.get("blocks") or {})
    except StudioError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception as exc:  # surface a bad graph without 500-ing
        return JsonResponse({"error": f"Could not queue pipeline: {exc}"}, status=400)

    return JsonResponse({"tasks": queued})


@login_required
def list_templates(request):
    """The user's saved Studio graphs for the load dropdown, tagged pipeline vs block so
    the canvas can list them in separate sections."""
    return JsonResponse({"templates": studio_ops.list_graphs(request.user)})


@login_required
@require_POST
def save_template(request):
    """Persist the current Studio graph (a Drawflow export) as a named JSON template
    file on the user's account, so it can be reloaded, exported, or published."""
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid request body."}, status=400)

    name = safe_name(payload.get("name", ""))
    if not name:
        return JsonResponse({"error": "Enter a valid template name."}, status=400)

    graph = payload.get("graph")
    if not isinstance(graph, dict):
        return JsonResponse({"error": "Missing graph data."}, status=400)

    root = user_template_root(request.user)
    path = resolve_safe_path(root, name, ".json")
    if path is None:
        return JsonResponse({"error": "Invalid template name."}, status=400)

    # Any nested block instances this graph uses travel with it, keyed by name, so a
    # boundary wired straight into one types correctly and the graph stays portable.
    nested_blocks = {n: {"header": b["header"], "body": b["body"]}
                     for n, b in (payload.get("blocks") or {}).items()}
    if nested_blocks:
        graph["blocks"] = nested_blocks

    # Saving a block derives its interface from its boundary wiring and bumps its
    # version, which is what pipelines pin when they embed a frozen copy.
    if payload.get("is_block"):
        simple = studio_ops.from_drawflow(graph)
        try:
            header = block_ops.derive_interface(simple["nodes"], simple["edges"], name=name,
                                                blocks=nested_blocks)
        except block_ops.BlockError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        previous = 0
        if path.exists():
            try:
                previous = int((json.loads(path.read_text(encoding="utf-8")).get("block") or {})
                               .get("version", 0))
            except (ValueError, OSError):
                previous = 0
        header["version"] = previous + 1
        graph["block"] = header
        graph["body"] = block_ops.definition_body(simple["nodes"], simple["edges"])

    path.write_text(json.dumps(graph), encoding="utf-8")
    set_description(root, name, payload.get("description", ""))
    return JsonResponse({"ok": True, "name": name, "block": graph.get("block")})


@login_required
def load_template(request, name):
    """Return a saved template's Drawflow graph so the Studio can import it."""
    root = user_template_root(request.user)
    path = resolve_safe_path(root, name, ".json")
    if path is None or not path.exists():
        raise Http404("Template not found.")
    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return JsonResponse({"error": "Template is corrupt."}, status=400)
    stale = block_ops.stale_blocks(
        {n: {"header": b["header"]} for n, b in (graph.get("blocks") or {}).items()},
        studio_ops.block_library(request.user))
    return JsonResponse({"name": name, "graph": graph, "stale": stale,
                         "description": get_description(root, name)})


# --- Synthesize: research-paper documents (block-model JSON) -------------------
@login_required
def list_papers(request):
    """The user's saved papers (name + description) for the open/library UI."""
    return JsonResponse({"papers": list_user_files(request.user, "paper")})


@login_required
@require_POST
def save_paper(request):
    """Persist a Synthesize paper (its block-model JSON `doc`) as a named file on
    the user's account, so it can be reopened, exported, published, or built."""
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid request body."}, status=400)

    name = safe_name(payload.get("name", ""))
    if not name:
        return JsonResponse({"error": "Enter a valid paper name."}, status=400)

    doc = payload.get("doc")
    if not isinstance(doc, dict):
        return JsonResponse({"error": "Missing document data."}, status=400)

    root = user_paper_root(request.user)
    path = resolve_safe_path(root, name, ".json")
    if path is None:
        return JsonResponse({"error": "Invalid paper name."}, status=400)

    path.write_text(json.dumps(doc), encoding="utf-8")
    set_description(root, name, payload.get("description", ""))
    return JsonResponse({"ok": True, "name": name})


@login_required
def load_paper(request, name):
    """Return a saved paper's block-model JSON so the editor can reopen it."""
    root = user_paper_root(request.user)
    path = resolve_safe_path(root, name, ".json")
    if path is None or not path.exists():
        raise Http404("Paper not found.")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return JsonResponse({"error": "Paper is corrupt."}, status=400)
    return JsonResponse({"name": name, "doc": doc, "description": get_description(root, name)})


@login_required
@require_POST
def build_paper(request):
    """Render a paper's block model into a self-contained, interactive HTML file
    and write it right alongside the paper's own document so it can be viewed,
    published, downloaded — or embedded as a figure in another paper. Builds from
    the posted `doc` (the live editor state) so the user need not save first."""
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid request body."}, status=400)

    doc = payload.get("doc")
    if not isinstance(doc, dict):
        # Fall back to a saved paper by name.
        name = safe_name(payload.get("name", ""))
        root = user_paper_root(request.user)
        path = resolve_safe_path(root, name, ".json") if name else None
        if path is None or not path.exists():
            return JsonResponse({"error": "Missing document data."}, status=400)
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return JsonResponse({"error": "Paper is corrupt."}, status=400)

    output_name = safe_name(payload.get("output_name") or payload.get("name") or doc.get("title") or "")
    if not output_name:
        return JsonResponse({"error": "Give the built report a valid name."}, status=400)

    paper_root = user_paper_root(request.user)
    try:
        # A figure may name a plain chart (lives with its Studio recipe) or another
        # paper's own built report (lives with that paper's document) -- search both.
        html = build_paper_html(doc, [str(user_template_root(request.user)), str(paper_root)])
    except Exception as exc:  # keep a bad doc from 500ing the whole request
        return JsonResponse({"error": f"Build failed: {exc}"}, status=400)

    out_path = resolve_html_path(output_name, str(paper_root))
    out_path.write_text(html, encoding="utf-8")
    set_description(paper_root, output_name, payload.get("description", "") or f"Built from paper “{output_name}”.")
    return JsonResponse({"ok": True, "name": output_name})


@login_required
@require_POST
def revoke_api_key(request, key_id):
    api_key = ApiKey.objects.filter(pk=key_id, user=request.user).first()
    if api_key is None:
        messages.error(request, "API key not found.")
    elif not api_key.is_active:
        messages.error(request, "That API key is already revoked.")
    else:
        api_key.revoke()
        # If the agent was using this key, forget it so a fresh one is minted
        # on the next chat message instead of authenticating with a dead key.
        if request.session.get("agent_api_key_hash") == api_key.hashed_key:
            request.session.pop("agent_api_key", None)
            request.session.pop("agent_api_key_hash", None)
        messages.success(request, f"Revoked API key “{api_key.name}”.")
    return redirect("dashboard")


def _ensure_agent_api_key(request) -> str:
    """Return a live raw API key for the agent, minting one if the cached key is
    missing or has since been revoked. The raw value is kept in the session (the
    only place the un-hashed key survives after creation)."""
    raw_key = request.session.get("agent_api_key")
    if raw_key and resolve_api_key(raw_key) is not None:
        return raw_key
    api_key, raw_key = create_api_key(request.user, "Dashboard agent")
    request.session["agent_api_key"] = raw_key
    # Remember which stored key backs the agent so a later revoke can clear it.
    request.session["agent_api_key_hash"] = api_key.hashed_key
    return raw_key


@login_required
@require_POST
def agent_chat(request):
    message = (request.POST.get("message") or "").strip()
    if not message:
        return JsonResponse({"error": "Enter a message."}, status=400)
    if not genai_installed():
        return JsonResponse(
            {"error": "The assistant is unavailable: the google-genai package is not installed."},
            status=503,
        )

    settings = _get_agent_settings(request.user)
    if not settings.has_key:
        return JsonResponse(
            {"error": "Add your Gemini API key in Settings to use the assistant."},
            status=400,
        )

    history = request.session.get("agent_history", [])
    try:
        turn = run_agent_turn(
            settings.gemini_api_key,
            settings.model,
            _ensure_agent_api_key(request),
            history,
            message,
            context=_agent_context(request),
        )
    except AgentError as exc:
        return JsonResponse({"error": str(exc)}, status=502)

    history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": turn["reply"]},
    ]
    request.session["agent_history"] = history[-AGENT_HISTORY_LIMIT:]
    # `tools` lets the front end refresh whatever the agent just changed (reopen the
    # paper it edited, reload the pipeline list) instead of the user hitting reload.
    return JsonResponse({"reply": turn["reply"], "tools": turn["tools"]})


def _agent_context(request) -> str:
    """What the user is looking at right now, handed to the model each turn so
    "add a conclusion section" resolves to the paper that is actually open."""
    tab = (request.POST.get("tab") or "").strip()
    paper = (request.POST.get("paper") or "").strip()
    bits = []
    if tab:
        bits.append(f"The user is on the {tab} tab.")
    if paper:
        bits.append(f'The paper open in the Synthesize editor is "{paper}" '
                    "-- when they say “the paper”/“this paper”, they mean that one. "
                    "Edits you make to it appear in their editor as soon as you finish.")
    elif tab == "synthesize":
        bits.append("No saved paper is open in the editor yet (it holds an unsaved draft).")
    return " ".join(bits)


@login_required
@require_POST
def agent_reset(request):
    request.session.pop("agent_history", None)
    return JsonResponse({"ok": True})


def _get_agent_settings(user) -> AgentSettings:
    settings, _ = AgentSettings.objects.get_or_create(user=user)
    return settings


def _get_external_api_settings(user) -> ExternalApiSettings:
    settings, _ = ExternalApiSettings.objects.get_or_create(user=user)
    return settings


@login_required
def account_settings(request):
    context = {
        "username_form": UsernameForm(instance=request.user),
        "password_form": PasswordChangeForm(request.user),
        "agent_form": AgentSettingsForm(instance=_get_agent_settings(request.user)),
        "external_api_form": ExternalApiSettingsForm(instance=_get_external_api_settings(request.user)),
        "is_staff": request.user.is_staff,
        "is_superuser": request.user.is_superuser,
    }
    return render(request, "portal/settings.html", context)


@login_required
@require_POST
def update_username(request):
    old_folder = storage_folder_name(request.user)
    form = UsernameForm(request.POST, instance=request.user)
    if not form.is_valid():
        for error in form.errors.get("username", ["Could not update username."]):
            messages.error(request, error)
        return redirect("account_settings")

    user = form.save()
    # Keep the user's storage folder in sync with their (username-derived) name.
    rename_user_storage(old_folder, storage_folder_name(user))
    messages.success(request, "Username updated.")
    return redirect("account_settings")


@login_required
@require_POST
def change_password(request):
    form = PasswordChangeForm(request.user, request.POST)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
        return redirect("account_settings")

    user = form.save()
    # Persisting a new password rotates the session hash; refresh it so the user
    # isn't logged out.
    update_session_auth_hash(request, user)
    messages.success(request, "Password changed.")
    return redirect("account_settings")


@login_required
@require_POST
def update_agent_settings(request):
    form = AgentSettingsForm(request.POST, instance=_get_agent_settings(request.user))
    if not form.is_valid():
        messages.error(request, "Could not save assistant settings.")
        return redirect("account_settings")

    form.save()
    messages.success(request, "Assistant settings saved.")
    return redirect("account_settings")


@login_required
@require_POST
def update_external_api_settings(request):
    form = ExternalApiSettingsForm(request.POST, instance=_get_external_api_settings(request.user))
    if not form.is_valid():
        messages.error(request, "Could not save data-source settings.")
        return redirect("account_settings")

    form.save()
    messages.success(request, "Data-source settings saved.")
    return redirect("account_settings")
