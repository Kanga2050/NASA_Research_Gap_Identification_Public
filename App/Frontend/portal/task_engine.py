from __future__ import annotations

import importlib
import os
import queue
import threading
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from typing import Any, Callable

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "App.Frontend.webapp.settings")

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
if project_root not in sys.path:
    sys.path.append(project_root)

import django

django.setup()

from django.utils import timezone as django_timezone

from .models import TaskRecord

shared_task_registry: dict[str, dict[str, Any]] = {}
pending_tasks: queue.Queue[str] = queue.Queue()
active_users: set[int] = set()
active_count = 0
task_condition = threading.Condition()
dispatcher_started = False
max_parallel_tasks = int(os.environ.get("DJANGO_MAX_PARALLEL_TASKS", "4"))
# Hard ceiling on how many tasks the in-memory registry retains. Evicted entries
# are transparently rebuilt from the database on the next status poll, so this
# only bounds memory - it never loses data.
MAX_REGISTRY_TASKS = 1000


def get_iso_time() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class PrintCatcher:
    def __init__(self, registry: dict[str, dict[str, Any]], task_id: str):
        self.registry = registry
        self.task_id = task_id
        self.terminal = sys.__stdout__

    def write(self, message: str):
        self.terminal.write(message)
        cleaned_message = message.strip()
        if cleaned_message and self.task_id in self.registry:
            self.registry[self.task_id]["latest_print"] = cleaned_message
            self.registry[self.task_id]["lastUpdatedAt"] = get_iso_time()

    def flush(self):
        self.terminal.flush()


def _enforce_registry_limit() -> None:
    # Drop the oldest entries (insertion order) once the registry grows past its
    # ceiling. Popped tasks are rehydrated from the DB whenever they're polled.
    while len(shared_task_registry) > MAX_REGISTRY_TASKS:
        try:
            oldest_key = next(iter(shared_task_registry))
        except StopIteration:
            return
        shared_task_registry.pop(oldest_key, None)


def _update_registry(task: TaskRecord) -> None:
    # Merge into any existing entry rather than replacing it outright -
    # PrintCatcher.write() stashes "latest_print" on this same dict, and a
    # blind overwrite (e.g. from a status poll) would erase it on every call.
    entry = shared_task_registry.setdefault(task.task_id, {})
    entry.update({
        "task_id": task.task_id,
        "user_id": task.user_id,
        "status": task.status,
        "function_name": task.function_name,
        "createdAt": task.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if task.created_at else get_iso_time(),
        "lastUpdatedAt": task.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ") if task.updated_at else get_iso_time(),
        "error": task.error,
    })
    _enforce_registry_limit()


def _refresh_task(task_id: str) -> TaskRecord:
    task = TaskRecord.objects.get(task_id=task_id)
    _update_registry(task)
    return task


def _ensure_dispatcher_started() -> None:
    global dispatcher_started
    if dispatcher_started:
        return

    dispatcher_started = True
    threading.Thread(target=_dispatcher_loop, daemon=True, name="PerUserTaskDispatcher").start()


def _dispatcher_loop() -> None:
    global active_count
    while True:
        task_id = pending_tasks.get()
        try:
            task = TaskRecord.objects.select_related("user").get(task_id=task_id)
            with task_condition:
                while task.user_id in active_users or active_count >= max_parallel_tasks:
                    task_condition.wait(timeout=1.0)
                active_users.add(task.user_id)
                active_count += 1

            threading.Thread(target=_run_task, args=(task.task_id,), daemon=True, name=f"Task-{task.task_id}").start()
        finally:
            pending_tasks.task_done()


# Maps a queued function name to its "module.path:attribute". Kept as strings
# so the (often heavy, ML-laden) backend module is only imported when a task of
# that type actually runs, not when this module is loaded.
CALLABLE_PATHS = {
    "embed_text": "App.Backend.Annotation_Functions.Embed_Text:embed_text",
    "reduce_dimensionality": "App.Backend.Annotation_Functions.Reduce_Dimensionality:reduce_dimensionality",
    "cluster": "App.Backend.Annotation_Functions.Cluster:cluster",
    "distance_map": "App.Backend.Visualization_Functions.Distance_Map:distance_map",
    "keyword_score": "App.Backend.Annotation_Functions.Keyword_Score:keyword_score",
    "semantic_score": "App.Backend.Annotation_Functions.Semantic_Score:semantic_score",
    "hybrid_score": "App.Backend.Annotation_Functions.Hybrid_Score:hybrid_score",
    "numerical_filter": "App.Backend.Distillation_Functions.Numerical_Filter:numerical_filter",
    "openalex_scraper": "App.Backend.Import_Data.OpenAlex_Scraper:openalex_scraper",
    # Distillation
    "categorical_filter": "App.Backend.Distillation_Functions.Categorical_Filter:categorical_filter",
    "combine_csvs": "App.Backend.Distillation_Functions.Combine_Csvs:combine_csvs",
    "aggregate_dictionary": "App.Backend.Distillation_Functions.Aggregate_Dictionary:aggregate_dictionary",
    "group_aggregate": "App.Backend.Distillation_Functions.Group_Aggregate:group_aggregate",
    "top_n_by_column": "App.Backend.Distillation_Functions.Top_N_By_Column:top_n_by_column",
    "deduplicate": "App.Backend.Distillation_Functions.Deduplicate:deduplicate",
    "select_columns": "App.Backend.Distillation_Functions.Select_Columns:select_columns",
    "cross_tab": "App.Backend.Distillation_Functions.Cross_Tab:cross_tab",
    "arithmetic": "App.Backend.Distillation_Functions.Arithmetic:arithmetic",
    # Annotation
    "word_frequency": "App.Backend.Annotation_Functions.Word_Frequency:word_frequency",
    "label_topics": "App.Backend.Annotation_Functions.Label_Topics:label_topics",
    "text_length": "App.Backend.Annotation_Functions.Text_Length:text_length",
    "extract_year": "App.Backend.Annotation_Functions.Extract_Year:extract_year",
    "to_date": "App.Backend.Annotation_Functions.To_Date:to_date",
    "normalize_column": "App.Backend.Annotation_Functions.Normalize_Column:normalize_column",
    # Visualization
    "bar_chart": "App.Backend.Visualization_Functions.Bar_Chart:bar_chart",
    "scatter_plot": "App.Backend.Visualization_Functions.Scatter_Plot:scatter_plot",
    "histogram": "App.Backend.Visualization_Functions.Histogram:histogram",
    "line_chart": "App.Backend.Visualization_Functions.Line_Chart:line_chart",
    "box_plot": "App.Backend.Visualization_Functions.Box_Plot:box_plot",
    "heatmap": "App.Backend.Visualization_Functions.Heatmap:heatmap",
    "pie_chart": "App.Backend.Visualization_Functions.Pie_Chart:pie_chart",
}


def _deserialize_callable(function_name: str) -> Callable[..., Any]:
    if function_name not in CALLABLE_PATHS:
        raise KeyError(function_name)
    module_path, attribute = CALLABLE_PATHS[function_name].split(":")
    return getattr(importlib.import_module(module_path), attribute)


def _set_status(task_id: str, status: str, **update_fields: Any) -> None:
    """Persist a status change and mirror it into the in-memory registry (which
    the status-poll endpoint reads), keeping DB and registry in lock-step."""
    TaskRecord.objects.filter(task_id=task_id).update(status=status, **update_fields)
    _refresh_task(task_id)
    shared_task_registry[task_id]["status"] = status


def _run_task(task_id: str) -> None:
    global active_count
    task = TaskRecord.objects.select_related("user").get(task_id=task_id)
    try:
        _set_status(task_id, TaskRecord.Status.WORKING, started_at=django_timezone.now())
        print(f"[Task Engine] Running task {task_id} ({task.function_name}) for user {task.user_id}...")

        catcher = PrintCatcher(shared_task_registry, task_id)
        with redirect_stdout(catcher):
            func = _deserialize_callable(task.function_name)
            func(*task.args_json, **task.kwargs_json)

        if TaskRecord.objects.get(task_id=task_id).status == TaskRecord.Status.CANCELLED:
            print(f"[Task Engine] Task {task_id} was cancelled during runtime.")
            return

        _set_status(task_id, TaskRecord.Status.COMPLETED, finished_at=django_timezone.now(), error="")
        shared_task_registry[task_id]["final_result"] = f"Success: {task.function_name} completed."
    except Exception as exc:
        _set_status(task_id, TaskRecord.Status.FAILED, finished_at=django_timezone.now(), error=str(exc))
        shared_task_registry[task_id]["error"] = str(exc)
    finally:
        with task_condition:
            active_users.discard(task.user_id)
            active_count = max(0, active_count - 1)
            task_condition.notify_all()


def queue_user_task(user, function_name: str, *args, **kwargs) -> dict[str, Any]:
    _ensure_dispatcher_started()
    task = TaskRecord.objects.create(
        user=user,
        task_id=os.urandom(16).hex(),
        function_name=function_name,
        status=TaskRecord.Status.QUEUED,
        args_json=list(args),
        kwargs_json=kwargs,
    )
    _update_registry(task)
    pending_tasks.put(task.task_id)
    return {"task_id": task.task_id, "status": task.status}


def get_task_status(task_id: str, user=None) -> dict[str, Any]:
    try:
        task = TaskRecord.objects.get(task_id=task_id)
    except TaskRecord.DoesNotExist:
        return {"error": "Task not found."}

    if user is not None and task.user_id != user.id:
        return {"error": "Task not found."}

    _update_registry(task)
    return shared_task_registry[task_id]


def get_task_history(user=None, limit: int = 20) -> list[dict[str, Any]]:
    qs = TaskRecord.objects.select_related("user").order_by("-created_at")
    if user is not None:
        qs = qs.filter(user=user)
    return [
        {
            "task_id": task.task_id,
            "status": task.status,
            "function_name": task.function_name,
            "createdAt": task.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "lastUpdatedAt": task.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "error": task.error,
        }
        for task in qs[:limit]
    ]


def get_active_tasks(user, limit: int = 50) -> list[dict[str, Any]]:
    """The user's currently ongoing (working) and scheduled (queued) tasks,
    oldest-queued first so the FIFO order is visible. Shared by the Dashboard and
    Studio live task panels so both tabs reflect the same queue in real time."""
    qs = (
        TaskRecord.objects.filter(
            user=user,
            status__in=[TaskRecord.Status.WORKING, TaskRecord.Status.QUEUED],
        )
        .order_by("created_at")[:limit]
    )
    tasks = []
    for task in qs:
        entry = shared_task_registry.get(task.task_id, {})
        tasks.append({
            "task_id": task.task_id,
            "status": task.status,
            "function_name": task.function_name,
            "createdAt": task.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "latest_print": entry.get("latest_print", ""),
        })
    return tasks