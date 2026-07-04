import os
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
from .data_lookups import list_csv_columns, list_user_csv_names, list_user_html_names
from .forms import AgentSettingsForm, ApiKeyCreateForm, SignupForm, TaskSubmitForm, UsernameForm
from .models import AgentSettings, ApiKey, TaskRecord
from .output_preview import build_output_preview, get_latest_task, resolve_safe_path
from .services import create_api_key, resolve_api_key
from .task_engine import get_task_history, get_task_status, queue_user_task
from App.Frontend.webapp.storage import (
    rename_user_storage,
    storage_folder_name,
    user_csv_root,
    user_html_root,
    user_task_root,
)

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
        "api_keys": request.user.api_keys.order_by("-created_at"),
        "agent_ready": genai_installed(),
        "agent_has_key": _get_agent_settings(request.user).has_key,
        "agent_history": request.session.get("agent_history", []),
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
@require_POST
def import_file(request):
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
        reply = run_agent_turn(
            settings.gemini_api_key,
            settings.model,
            _ensure_agent_api_key(request),
            history,
            message,
        )
    except AgentError as exc:
        return JsonResponse({"error": str(exc)}, status=502)

    history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ]
    request.session["agent_history"] = history[-AGENT_HISTORY_LIMIT:]
    return JsonResponse({"reply": reply})


@login_required
@require_POST
def agent_reset(request):
    request.session.pop("agent_history", None)
    return JsonResponse({"ok": True})


def _get_agent_settings(user) -> AgentSettings:
    settings, _ = AgentSettings.objects.get_or_create(user=user)
    return settings


@login_required
def account_settings(request):
    settings = _get_agent_settings(request.user)
    context = {
        "username_form": UsernameForm(instance=request.user),
        "password_form": PasswordChangeForm(request.user),
        "agent_form": AgentSettingsForm(instance=settings),
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
