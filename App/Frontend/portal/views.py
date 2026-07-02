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
    suffix = Path(safe_name).suffix.lower()
    if suffix == ".csv":
        target_root = user_csv_root(request.user)
    elif suffix == ".html":
        target_root = user_html_root(request.user)
    else:
        messages.error(request, "Only .csv and .html files can be imported.")
        return redirect("dashboard")

    if not safe_name or safe_name in {".", ".."}:
        messages.error(request, "Invalid file name.")
        return redirect("dashboard")

    destination = target_root / safe_name
    with destination.open("wb") as out:
        for chunk in upload.chunks():
            out.write(chunk)

    messages.success(request, f"Imported {safe_name}.")
    return redirect("dashboard")


@login_required
def export_file(request, kind, name):
    if kind == "csv":
        root = user_csv_root(request.user)
        suffix = ".csv"
    elif kind == "html":
        root = user_html_root(request.user)
        suffix = ".html"
    else:
        raise Http404("Unknown export kind.")

    file_path = resolve_safe_path(root, name, suffix)
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


def _queue_task_for_user(user, action: str, cleaned: dict):
    csv_root = str(user_csv_root(user))
    html_root = str(user_html_root(user))
    if action == "embed_text":
        return queue_user_task(user, action, cleaned["csv_name"], cleaned.get("text_column") or "abstract", "abstract_embedding", cleaned.get("model_name") or "allenai/specter2_base", csv_root=csv_root)
    if action == "reduce_dimensionality":
        return queue_user_task(user, action, cleaned["csv_name"], cleaned.get("embedding_column") or "abstract_embedding", cleaned.get("output_column") or "2d", cleaned.get("n_components") or 2, csv_root=csv_root)
    if action == "cluster":
        return queue_user_task(user, action, cleaned["csv_name"], cleaned.get("embedding_column") or "5d", cleaned.get("output_column") or "topic_id", cleaned.get("min_cluster_size") or 32, cleaned.get("min_samples") or 8, csv_root=csv_root)
    if action == "distance_map":
        return queue_user_task(user, action, cleaned["csv_name"], cleaned.get("topic_column") or "topic_id", cleaned.get("text_column") or "abstract", cleaned.get("embedding_column") or "2d", cleaned.get("output_name") or f"{cleaned['csv_name']}_Topics", csv_root=csv_root, html_root=html_root)
    if action == "keyword_score":
        return queue_user_task(user, action, cleaned["csv_name"], cleaned.get("query") or "", cleaned.get("text_column") or "abstract", cleaned.get("output_column") or "kw", csv_root=csv_root)
    if action == "semantic_score":
        return queue_user_task(user, action, cleaned["csv_name"], cleaned.get("query") or "", cleaned.get("embedding_column") or "abstract_embedding", cleaned.get("output_column") or "sem", csv_root=csv_root)
    if action == "hybrid_score":
        return queue_user_task(user, action, cleaned["csv_name"], cleaned.get("keyword_col") or "kw", cleaned.get("semantic_col") or "sem", cleaned.get("output_column") or "hybrid", csv_root=csv_root)
    if action == "numerical_filter":
        return queue_user_task(user, action, cleaned.get("source_csv") or cleaned["csv_name"], cleaned.get("output_csv") or "Filtered_Output", cleaned.get("target_score_column") or "hybrid", cleaned.get("threshold") or 0.7, csv_root=csv_root)
    if action == "openalex_scraper":
        return queue_user_task(user, action, cleaned.get("topic") or "space biology", cleaned.get("csv_name") or "scraped", cleaned.get("limit") or 10000, csv_root=csv_root)
    raise ValueError("Unknown action")


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
