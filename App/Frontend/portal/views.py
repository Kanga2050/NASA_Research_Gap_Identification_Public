import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import ApiKeyCreateForm, TaskSubmitForm
from .services import create_api_key
from .task_engine import get_task_history, queue_user_task
from App.Frontend.webapp.storage import user_csv_root, user_html_root, user_task_root


@login_required
def dashboard(request):
    csv_root = user_csv_root(request.user)
    html_root = user_html_root(request.user)
    task_root = user_task_root(request.user)
    csv_files = sorted([name for name in os.listdir(csv_root) if name.endswith(".csv")])
    html_files = sorted([name for name in os.listdir(html_root) if name.endswith(".html")])
    context = {
        "api_key_form": ApiKeyCreateForm(),
        "task_form": TaskSubmitForm(),
        "csv_root": csv_root,
        "html_root": html_root,
        "task_root": task_root,
        "csv_files": csv_files,
        "html_files": html_files,
        "tasks": get_task_history(user=request.user, limit=25),
    }
    return render(request, "portal/dashboard.html", context)


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