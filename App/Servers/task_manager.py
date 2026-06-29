import queue
import threading
from datetime import datetime, timezone
from typing import Dict, Any

# --- Universal State & Queue ---
shared_task_registry: Dict[str, Any] = {}
task_queue: queue.Queue = queue.Queue()

def get_iso_time() -> str:
    """Returns the current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def run_shared_task(task_id: str, function_name: str, func, *args, **kwargs):
    """Executes a pipeline step and logs state to the shared registry."""
    try:
        shared_task_registry[task_id]["status"] = "working"
        shared_task_registry[task_id]["lastUpdatedAt"] = get_iso_time()
        print(f"[Shared Engine] Running task {task_id} ({function_name})...")
        
        # Execute the actual pipeline function
        func(*args, **kwargs)
        
        # Check if the task was cancelled while running
        if shared_task_registry[task_id]["status"] == "cancelled":
            print(f"[Shared Engine] Task {task_id} was cancelled during runtime.")
            return

        shared_task_registry[task_id]["status"] = "completed"
        shared_task_registry[task_id]["lastUpdatedAt"] = get_iso_time()
        shared_task_registry[task_id]["final_result"] = f"Success: {function_name} completed."
    except Exception as e:
        shared_task_registry[task_id]["status"] = "failed"
        shared_task_registry[task_id]["lastUpdatedAt"] = get_iso_time()
        shared_task_registry[task_id]["error"] = str(e)

def _queue_worker():
    """A persistent background thread that processes the queue sequentially."""
    while True:
        # Blocks until an item is pushed into the queue
        task_id, function_name, func, args, kwargs = task_queue.get()
        
        try:
            # Skip if the user cancelled it while it was waiting in the queue
            if shared_task_registry.get(task_id, {}).get("status") == "cancelled":
                print(f"[Shared Engine] Skipping task {task_id} ({function_name}) - pre-cancelled.")
                continue
                
            run_shared_task(task_id, function_name, func, *args, **kwargs)
        finally:
            task_queue.task_done()

# Start the worker thread exactly once when this module is loaded
worker_thread = threading.Thread(target=_queue_worker, daemon=True, name="SequentialWorker")
worker_thread.start()

def add_task_to_queue(task_id: str, function_name: str, func, *args, **kwargs):
    """Helper to safely push an execution package onto the background FIFO queue."""
    task_queue.put((task_id, function_name, func, args, kwargs))