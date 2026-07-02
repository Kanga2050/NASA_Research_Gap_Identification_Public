import os
from pathlib import Path

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.clickjacking import xframe_options_sameorigin

from .data_lookups import list_csv_columns, list_user_csv_names, list_user_html_names
from .forms import ApiKeyCreateForm, SignupForm, TaskSubmitForm
from .models import TaskRecord
from .output_preview import build_output_preview, get_latest_task, resolve_safe_path
from .services import create_api_key
from .task_engine import get_task_history, get_task_status, queue_user_task
from App.Frontend.webapp.storage import user_csv_root, user_html_root, user_task_root

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
]

# Maps an import/export "kind" (also the file extension) to the storage-root
# accessor and dotted suffix for that file type. Shared by import_file/export_file.
KIND_ROOTS = {
    "csv": (user_csv_root, ".csv"),
    "html": (user_html_root, ".html"),
}


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


@login_required
def dashboard(request):
    csv_root = user_csv_root(request.user)
    html_root = user_html_root(request.user)
    task_root = user_task_root(request.user)
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

    context = {
        "api_key_form": ApiKeyCreateForm(),
        "task_form": TaskSubmitForm(),
        "csv_root": csv_root,
        "html_root": html_root,
        "task_root": task_root,
        "csv_names": csv_names,
        "html_names": html_names,
        "column_field_names": COLUMN_FIELD_NAMES,
        "tasks": get_task_history(user=request.user, limit=25),
        "latest_task": latest_task,
        "latest_output": latest_output,
        "latest_task_in_progress": latest_task_in_progress,
    }
    return render(request, "portal/dashboard.html", context)


@login_required
def csv_columns(request, name):
    return JsonResponse({"columns": list_csv_columns(request.user, name)})


@login_required
def task_status(request, task_id):
    return JsonResponse(get_task_status(task_id, user=request.user))


@login_required
@xframe_options_sameorigin
def preview_output_html(request, name):
    html_path = resolve_safe_path(user_html_root(request.user), name, ".html")
    if html_path is None or not html_path.exists():
        raise Http404("Visualization not found.")

    return HttpResponse(html_path.read_text(encoding="utf-8"), content_type="text/html")


@login_required
def import_file(request):
    if request.method != "POST":
        return redirect("dashboard")

    upload = request.FILES.get("upload")
    if not upload:
        messages.error(request, "Choose a file to import.")
        return redirect("dashboard")

    safe_name = os.path.basename(upload.name)
    if not safe_name or safe_name in {".", ".."}:
        messages.error(request, "Invalid file name.")
        return redirect("dashboard")

    kind = Path(safe_name).suffix.lower().lstrip(".")
    if kind not in KIND_ROOTS:
        messages.error(request, "Only .csv and .html files can be imported.")
        return redirect("dashboard")

    destination = KIND_ROOTS[kind][0](request.user) / safe_name
    with destination.open("wb") as out:
        for chunk in upload.chunks():
            out.write(chunk)

    messages.success(request, f"Imported {safe_name}.")
    return redirect("dashboard")


@login_required
def export_file(request, kind, name):
    if kind not in KIND_ROOTS:
        raise Http404("Unknown export kind.")

    root_fn, suffix = KIND_ROOTS[kind]
    file_path = resolve_safe_path(root_fn(request.user), name, suffix)
    if file_path is None or not file_path.exists():
        raise Http404("File not found.")

    return FileResponse(file_path.open("rb"), as_attachment=True, filename=f"{name}{suffix}")


@login_required
def issue_api_key(request):
    if request.method != "POST":
        return redirect("dashboard")

    form = ApiKeyCreateForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Provide a valid API key name.")
        return redirect("dashboard")

    _, raw_key = create_api_key(request.user, form.cleaned_data["name"])
    request.session["last_api_key"] = raw_key
    messages.success(request, "API key created. It is shown once below.")
    return redirect("dashboard")


# Declarative spec for each task action, replacing a long if/elif ladder.
#   "roots": which storage roots the backend function receives as *_root kwargs.
#   "args":  the positional args passed to queue_user_task, each a
#            (form_field, default) pair. A None field means `default` is a
#            literal constant; otherwise the submitted value is used when
#            truthy, falling back to `default` (which may be a callable taking
#            the cleaned form data, for defaults computed from other fields).
TASK_SPECS = {
    "embed_text": {"roots": ["csv"], "args": [("csv_name", ""), ("text_column", "abstract"), (None, "abstract_embedding"), ("model_name", "allenai/specter2_base")]},
    "reduce_dimensionality": {"roots": ["csv"], "args": [("csv_name", ""), ("embedding_column", "abstract_embedding"), ("output_column", "2d"), ("n_components", 2)]},
    "cluster": {"roots": ["csv"], "args": [("csv_name", ""), ("embedding_column", "5d"), ("output_column", "topic_id"), ("min_cluster_size", 32), ("min_samples", 8)]},
    "distance_map": {"roots": ["csv", "html"], "args": [("csv_name", ""), ("topic_column", "topic_id"), ("text_column", "abstract"), ("embedding_column", "2d"), ("output_name", lambda c: f"{c['csv_name']}_Topics")]},
    "keyword_score": {"roots": ["csv"], "args": [("csv_name", ""), ("query", ""), ("text_column", "abstract"), ("output_column", "kw")]},
    "semantic_score": {"roots": ["csv"], "args": [("csv_name", ""), ("query", ""), ("embedding_column", "abstract_embedding"), ("output_column", "sem")]},
    "hybrid_score": {"roots": ["csv"], "args": [("csv_name", ""), ("keyword_col", "kw"), ("semantic_col", "sem"), ("output_column", "hybrid")]},
    "numerical_filter": {"roots": ["csv"], "args": [("source_csv", lambda c: c["csv_name"]), ("output_csv", "Filtered_Output"), ("target_score_column", "hybrid"), ("threshold", 0.7)]},
    "openalex_scraper": {"roots": ["csv"], "args": [("topic", "space biology"), ("csv_name", "scraped"), ("limit", 10000)]},
}

ROOT_BUILDERS = {"csv": user_csv_root, "html": user_html_root}


def _resolve_arg(cleaned: dict, field, default):
    if field is not None and cleaned.get(field):
        return cleaned[field]
    return default(cleaned) if callable(default) else default


def _queue_task_for_user(user, action: str, cleaned: dict):
    spec = TASK_SPECS.get(action)
    if spec is None:
        raise ValueError("Unknown action")
    args = [_resolve_arg(cleaned, field, default) for field, default in spec["args"]]
    root_kwargs = {f"{name}_root": str(ROOT_BUILDERS[name](user)) for name in spec["roots"]}
    return queue_user_task(user, action, *args, **root_kwargs)


@login_required
def submit_task(request):
    if request.method != "POST":
        return redirect("dashboard")

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
