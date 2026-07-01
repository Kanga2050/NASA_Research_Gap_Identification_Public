from __future__ import annotations

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


def _update_registry(task: TaskRecord) -> None:
    shared_task_registry[task.task_id] = {
        "task_id": task.task_id,
        "user_id": task.user_id,
        "status": task.status,
        "function_name": task.function_name,
        "createdAt": task.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if task.created_at else get_iso_time(),
        "lastUpdatedAt": task.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ") if task.updated_at else get_iso_time(),
        "error": task.error,
    }


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


def _deserialize_callable(function_name: str) -> Callable[..., Any]:
    if function_name == "embed_text":
        from App.Backend.Annotation_Functions.Embed_Text import embed_text

        return embed_text
    if function_name == "reduce_dimensionality":
        from App.Backend.Annotation_Functions.Reduce_Dimensionality import reduce_dimensionality

        return reduce_dimensionality
    if function_name == "cluster":
        from App.Backend.Annotation_Functions.Cluster import cluster

        return cluster
    if function_name == "distance_map":
        from App.Backend.Visualization_Functions.Distance_Map import distance_map

        return distance_map
    if function_name == "keyword_score":
        from App.Backend.Annotation_Functions.Keyword_Score import keyword_score

        return keyword_score
    if function_name == "semantic_score":
        from App.Backend.Annotation_Functions.Semantic_Score import semantic_score

        return semantic_score
    if function_name == "hybrid_score":
        from App.Backend.Annotation_Functions.Hybrid_Score import hybrid_score

        return hybrid_score
    if function_name == "numerical_filter":
        from App.Backend.Distillation_Functions.Numerical_Filter import numerical_filter

        return numerical_filter
    if function_name == "openalex_scraper":
        from App.Backend.Import_Data.OpenAlex_Scraper import openalex_scraper

        return openalex_scraper
    raise KeyError(function_name)


def _run_task(task_id: str) -> None:
    global active_count
    task = TaskRecord.objects.select_related("user").get(task_id=task_id)
    try:
        TaskRecord.objects.filter(task_id=task_id).update(status=TaskRecord.Status.WORKING, started_at=django_timezone.now())
        task = _refresh_task(task_id)
        shared_task_registry[task_id]["status"] = TaskRecord.Status.WORKING
        print(f"[Task Engine] Running task {task_id} ({task.function_name}) for user {task.user_id}...")

        catcher = PrintCatcher(shared_task_registry, task_id)
        with redirect_stdout(catcher):
            func = _deserialize_callable(task.function_name)
            func(*task.args_json, **task.kwargs_json)

        if TaskRecord.objects.get(task_id=task_id).status == TaskRecord.Status.CANCELLED:
            print(f"[Task Engine] Task {task_id} was cancelled during runtime.")
            return

        TaskRecord.objects.filter(task_id=task_id).update(status=TaskRecord.Status.COMPLETED, finished_at=django_timezone.now(), error="")
        _refresh_task(task_id)
        shared_task_registry[task_id]["status"] = TaskRecord.Status.COMPLETED
        shared_task_registry[task_id]["final_result"] = f"Success: {task.function_name} completed."
    except Exception as exc:
        TaskRecord.objects.filter(task_id=task_id).update(status=TaskRecord.Status.FAILED, finished_at=django_timezone.now(), error=str(exc))
        _refresh_task(task_id)
        shared_task_registry[task_id]["status"] = TaskRecord.Status.FAILED
        shared_task_registry[task_id]["error"] = str(exc)
    finally:
        with task_condition:
            if task.user_id in active_users:
                active_users.remove(task.user_id)
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