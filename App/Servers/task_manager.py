import sys
import queue
import threading
from contextlib import redirect_stdout
from datetime import datetime, timezone
from typing import Dict, Any

shared_task_registry: Dict[str, Any] = {}
task_queue: queue.Queue = queue.Queue()

def get_iso_time() -> str:
    """Returns the current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

class PrintCatcher:
    """A custom stream that logs printed messages to the registry and the terminal."""
    def __init__(self, registry: Dict[str, Any], task_id: str):
        self.registry = registry
        self.task_id = task_id
        # Keep a reference to the original console output
        self.terminal = sys.__stdout__ 

    def write(self, message: str):
        # 1. Print to the console normally
        self.terminal.write(message)
        
        # 2. Update the registry with the latest print (ignore empty newlines)
        cleaned_message = message.strip()
        if cleaned_message:
            # Ensure the task dict exists before updating
            if self.task_id in self.registry:
                self.registry[self.task_id]["latest_print"] = cleaned_message
                self.registry[self.task_id]["lastUpdatedAt"] = get_iso_time()

    def flush(self):
        # Required to fully emulate sys.stdout
        self.terminal.flush()

def run_shared_task(task_id: str, function_name: str, func, *args, **kwargs):
    """Executes a pipeline step and logs state to the shared registry."""
    try:
        shared_task_registry[task_id]["status"] = "working"
        shared_task_registry[task_id]["lastUpdatedAt"] = get_iso_time()
        print(f"[Shared Engine] Running task {task_id} ({function_name})...")
        
        # Intercept print statements within this context block
        catcher = PrintCatcher(shared_task_registry, task_id)
        with redirect_stdout(catcher):
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