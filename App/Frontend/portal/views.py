import json
import os
from collections import deque
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
    list_csv_columns,
    list_csv_columns_typed,
    list_user_csv_names,
    list_user_html_names,
)
from .forms import AgentSettingsForm, ApiKeyCreateForm, SignupForm, TaskSubmitForm, UsernameForm
from .graph_manifest import MANIFEST, PALETTE
from .models import AgentSettings, ApiKey, TaskRecord
from .output_preview import build_named_preview, build_output_preview, get_latest_task, resolve_safe_path
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
    "target_column",
    "dict_column",
    "group_column",
    "sort_column",
    "subset_column",
    "row_column",
    "column_column",
    "date_column",
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
        "active_tab": "dashboard",
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
    # `columns` (name list) stays for the dashboard form; `typed` adds inferred
    # wire types for the Studio node editor.
    typed = list_csv_columns_typed(request.user, name)
    return JsonResponse({"columns": [c["name"] for c in typed], "typed": typed})


@login_required
def task_status(request, task_id):
    return JsonResponse(get_task_status(task_id, user=request.user))


@login_required
def preview_output(request, kind, name):
    """JSON preview of any CSV/HTML file the signed-in user owns, for the
    center-column "view a previous output" dropdown."""
    return JsonResponse(build_named_preview(request.user, kind, name))


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
    "embed_text": {"roots": ["csv"], "args": [("csv_name", ""), ("text_column", "abstract"), ("output_column", "abstract_embedding"), ("model_name", "allenai/specter2_base")]},
    "reduce_dimensionality": {"roots": ["csv"], "args": [("csv_name", ""), ("embedding_column", "abstract_embedding"), ("output_column", "2d"), ("n_components", 2)]},
    "cluster": {"roots": ["csv"], "args": [("csv_name", ""), ("embedding_column", "5d"), ("output_column", "topic_id"), ("min_cluster_size", 32), ("min_samples", 8)]},
    "distance_map": {"roots": ["csv", "html"], "args": [("csv_name", ""), ("topic_column", "topic_id"), ("text_column", "abstract"), ("embedding_column", "2d"), ("output_name", lambda c: f"{c['csv_name']}_Topics"), ("chart_title", "")]},
    "keyword_score": {"roots": ["csv"], "args": [("csv_name", ""), ("query", ""), ("text_column", "abstract"), ("output_column", "kw")]},
    "semantic_score": {"roots": ["csv"], "args": [("csv_name", ""), ("query", ""), ("embedding_column", "abstract_embedding"), ("output_column", "sem")]},
    "hybrid_score": {"roots": ["csv"], "args": [("csv_name", ""), ("keyword_col", "kw"), ("semantic_col", "sem"), ("output_column", "hybrid")]},
    "numerical_filter": {"roots": ["csv"], "args": [("source_csv", lambda c: c["csv_name"]), ("output_csv", "Filtered_Output"), ("target_score_column", "hybrid"), ("threshold", 0.7)]},
    "openalex_scraper": {"roots": ["csv"], "args": [("topic", "space biology"), ("csv_name", "scraped"), ("limit", 10000)]},
    # Distillation
    "categorical_filter": {"roots": ["csv"], "args": [("source_csv", ""), ("output_csv", "Filtered_Output"), ("target_column", ""), ("expected_value", "")]},
    "combine_csvs": {"roots": ["csv"], "args": [("source_csvs", ""), ("output_csv", "Combined_Corpus"), ("source_column", "source")]},
    "aggregate_dictionary": {"roots": ["csv"], "args": [("source_csv", ""), ("output_csv", "Aggregated_Counts"), ("dict_column", "word_freq")]},
    "group_aggregate": {"roots": ["csv"], "args": [("source_csv", ""), ("output_csv", "Grouped_Output"), ("group_column", ""), ("value_column", ""), ("agg", "count"), ("exclude", "")]},
    "top_n_by_column": {"roots": ["csv"], "args": [("source_csv", ""), ("output_csv", "Top_N_Output"), ("sort_column", ""), ("n", 100), ("ascending", False)]},
    "deduplicate": {"roots": ["csv"], "args": [("source_csv", ""), ("output_csv", "Deduplicated_Output"), ("subset_column", "")]},
    "select_columns": {"roots": ["csv"], "args": [("source_csv", ""), ("output_csv", "Selected_Columns_Output"), ("columns", ""), ("drop", False)]},
    "cross_tab": {"roots": ["csv"], "args": [("source_csv", ""), ("output_csv", "Cross_Tab_Output"), ("row_column", ""), ("column_column", "")]},
    "arithmetic": {"roots": ["csv"], "args": [("source_csv", ""), ("output_csv", "Arithmetic_Output"), ("column_a", ""), ("operation", "divide"), ("operand", ""), ("new_column_name", "result"), ("group_by", "")]},
    # Annotation
    "word_frequency": {"roots": ["csv"], "args": [("csv_name", ""), ("text_column", "abstract"), ("new_column_name", "word_freq"), ("ngram", 1)]},
    "label_topics": {"roots": ["csv"], "args": [("csv_name", ""), ("topic_column", "topic_id"), ("text_column", "abstract"), ("new_column_name", "Topic_Label")]},
    "text_length": {"roots": ["csv"], "args": [("csv_name", ""), ("text_column", "abstract"), ("new_column_name", "length"), ("unit", "words")]},
    "extract_year": {"roots": ["csv"], "args": [("csv_name", ""), ("date_column", "publish_time"), ("new_column_name", "year")]},
    "to_date": {"roots": ["csv"], "args": [("csv_name", ""), ("date_column", "publish_time"), ("new_column_name", "date")]},
    "normalize_column": {"roots": ["csv"], "args": [("csv_name", ""), ("value_column", ""), ("new_column_name", "")]},
    # Visualization
    "bar_chart": {"roots": ["csv", "html"], "args": [("csv_name", ""), ("category_column", ""), ("value_column", ""), ("series_column", ""), ("chart_title", ""), ("output_name", lambda c: f"{c['csv_name']}_bar_chart"), ("top_n", 25), ("exclude", "")]},
    "scatter_plot": {"roots": ["csv", "html"], "args": [("csv_name", ""), ("x_column", ""), ("y_column", ""), ("color_column", ""), ("size_column", ""), ("coord_column", ""), ("chart_title", ""), ("output_name", lambda c: f"{c['csv_name']}_scatter")]},
    "histogram": {"roots": ["csv", "html"], "args": [("csv_name", ""), ("value_column", ""), ("bins", 30), ("chart_title", ""), ("output_name", lambda c: f"{c['csv_name']}_histogram"), ("color_column", ""), ("log_x", False), ("log_y", False)]},
    "line_chart": {"roots": ["csv", "html"], "args": [("csv_name", ""), ("x_column", ""), ("y_column", ""), ("color_column", ""), ("chart_title", ""), ("output_name", lambda c: f"{c['csv_name']}_line_chart")]},
    "box_plot": {"roots": ["csv", "html"], "args": [("csv_name", ""), ("value_column", ""), ("category_column", ""), ("chart_title", ""), ("output_name", lambda c: f"{c['csv_name']}_box_plot"), ("exclude", ""), ("log_y", False)]},
    "heatmap": {"roots": ["csv", "html"], "args": [("csv_name", ""), ("x_column", ""), ("y_column", ""), ("value_column", ""), ("chart_title", ""), ("output_name", lambda c: f"{c['csv_name']}_heatmap")]},
    "pie_chart": {"roots": ["csv", "html"], "args": [("csv_name", ""), ("category_column", ""), ("value_column", ""), ("chart_title", ""), ("output_name", lambda c: f"{c['csv_name']}_pie_chart"), ("top_n", 10), ("exclude", "")]},
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
def studio(request):
    """Visual scripting canvas: nodes wired into a pipeline, queued in dependency
    order by studio_run. Ships the function manifest and CSV names to the editor."""
    return render(request, "portal/studio.html", {
        "active_tab": "studio",
        "csv_names": list_user_csv_names(request.user),
        "manifest": {"nodes": MANIFEST, "palette": PALETTE},
    })


def _topo_sort(node_ids, edges):
    """Kahn topological sort over the table edges. Returns an ordered list of node
    ids, or None if the graph contains a cycle."""
    indeg = {nid: 0 for nid in node_ids}
    adj = {nid: [] for nid in node_ids}
    for edge in edges:
        src, dst = str(edge.get("from")), str(edge.get("to"))
        if src in indeg and dst in indeg:
            adj[src].append(dst)
            indeg[dst] += 1
    queue = deque(nid for nid in node_ids if indeg[nid] == 0)
    order = []
    while queue:
        nid = queue.popleft()
        order.append(nid)
        for nxt in adj[nid]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    return order if len(order) == len(node_ids) else None


def _coerce_number(value):
    """Studio sends form values as strings; turn numeric-widget values back into
    int/float so backend functions (e.g. bins, top_n) get real numbers."""
    text = str(value).strip()
    if text == "":
        return value
    try:
        return float(text) if ("." in text or "e" in text.lower()) else int(text)
    except ValueError:
        return value


@login_required
@require_POST
def studio_run(request):
    """Compile the node graph into queued tasks, in dependency (topological) order.

    Wires carry "carriage": a csv wire carries a table name, a column wire carries
    {csv, column}. We propagate carriage through the graph in topological order to
    resolve each function's source CSV (from its input wires) and column args, then
    queue via TASK_SPECS. Per-user FIFO execution in the task engine means enqueuing
    in topological order is sufficient for correct execution order -- no dependency
    machinery needed. Source/bridge nodes (__csv__, __column__) queue nothing.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid request body."}, status=400)

    nodes = {str(n.get("id")): n for n in payload.get("nodes", [])}
    edges = payload.get("edges", [])

    order = _topo_sort(list(nodes), edges)
    if order is None:
        return JsonResponse({"error": "The pipeline has a cycle -- remove a connection."}, status=400)

    # incoming[node] = list of (source_node, target_input_port_index)
    incoming = {nid: [] for nid in nodes}
    for edge in edges:
        src, dst = str(edge.get("from")), str(edge.get("to"))
        if dst in incoming and src in nodes:
            incoming[dst].append((src, int(edge.get("toPort", 0))))

    carry = {}  # node id -> its output carriage: {"wire","csv"[,"column"]}
    queued = []
    try:
        for nid in order:
            node = nodes[nid]
            entry = MANIFEST.get(node.get("action"))
            if entry is None:
                continue
            in_by_port = {port: carry.get(src) for src, port in incoming.get(nid, [])}

            if entry["special"] == "csv_input":
                carry[nid] = {"wire": "csv", "csv": node.get("csv", "")}
                continue
            if entry["special"] == "select_column":
                src = in_by_port.get(0) or {}
                carry[nid] = {"wire": "column", "csv": src.get("csv", ""), "column": node.get("column", "")}
                continue

            cleaned = dict(node.get("fields") or {})
            for pref in entry["prefs"]:
                if pref["widget"] == "number" and pref["param"] in cleaned:
                    cleaned[pref["param"]] = _coerce_number(cleaned[pref["param"]])

            source_csv, csv_inputs = "", []
            for i, inp in enumerate(entry["inputs"]):
                wire = in_by_port.get(i)
                if not wire:
                    continue
                if inp["wire"] == "csv":
                    csv_inputs.append(wire.get("csv", ""))
                    source_csv = source_csv or wire.get("csv", "")
                else:  # column wire -> its column name is the arg; its CSV seeds the source
                    cleaned[inp["param"]] = wire.get("column", "")
                    source_csv = source_csv or wire.get("csv", "")

            if entry["table_param"]:
                cleaned[entry["table_param"]] = source_csv or cleaned.get(entry["table_param"], "")
            if node.get("action") == "combine_csvs":
                cleaned["source_csvs"] = ",".join(c for c in csv_inputs if c)

            result = _queue_task_for_user(request.user, node["action"], cleaned)

            out = entry["output"]
            out_name = cleaned.get(out["param"]) or out.get("default", "")
            if entry["category"] == "annotation":
                carry[nid] = {"wire": "column", "csv": source_csv, "column": out_name}
            elif entry["category"] == "distillation":
                carry[nid] = {"wire": "csv", "csv": out_name}
            else:
                carry[nid] = {"wire": "none"}

            queued.append({
                "task_id": result["task_id"],
                "action": node["action"],
                "category": entry["category"],
                "output_name": out_name,
            })
    except Exception as exc:  # surface a bad graph without 500-ing
        return JsonResponse({"error": f"Could not queue pipeline: {exc}", "tasks": queued}, status=400)

    return JsonResponse({"tasks": queued})


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
