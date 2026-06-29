import sys
import os
import uuid
import threading
from datetime import datetime, timezone
from typing import Dict, Any
from fastmcp import FastMCP

current_dir = os.path.dirname(os.path.abspath(__file__))
target_path = os.path.abspath(os.path.join(current_dir, ".."))
if target_path not in sys.path:
    sys.path.append(target_path)

# Import all modules directly from your pipeline
from Backend.Annotation_Functions.Embedder import add_embeddings_in_place
from Backend.Annotation_Functions.Dimensionality_Reducer import reduce_embeddings_with_umap
from Backend.Annotation_Functions.Clustering import cluster_with_hdbscan
from Backend.Visualization_Functions.Distance_Map import generate_intertopic_distance_map
from Backend.Annotation_Functions.Keyword_Score import keyword_search
from Backend.Annotation_Functions.Semantic_Score import semantic_search
from Backend.Annotation_Functions.Hybrid_Score import hybrid_search
from Backend.Distillation_Functions.Numerical_Filtering import numerical_search

# Import getter functions
from Servers.Getter_Functions.list_html_files import list_html_files
from Servers.Getter_Functions.get_csv_catalog import get_csv_catalog
from Servers.Getter_Functions.get_csv_segment import get_csv_segment

mcp = FastMCP("Data Science Pipeline Agent Tools")

# --- MCP Task Engine ---
mcp_task_registry: Dict[str, Any] = {}

def get_iso_time():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def run_mcp_thread(task_id: str, function_name: str, func, *args, **kwargs):
    """Executes a pipeline step in a background thread."""
    try:
        mcp_task_registry[task_id]["status"] = "working"
        mcp_task_registry[task_id]["lastUpdatedAt"] = get_iso_time()
        print(f"[MCP Agent Engine] Running task {task_id} ({function_name})...")
        
        func(*args, **kwargs)
        
        mcp_task_registry[task_id]["status"] = "completed"
        mcp_task_registry[task_id]["lastUpdatedAt"] = get_iso_time()
        mcp_task_registry[task_id]["final_result"] = f"Success: {function_name} completed."
    except Exception as e:
        mcp_task_registry[task_id]["status"] = "failed"
        mcp_task_registry[task_id]["lastUpdatedAt"] = get_iso_time()
        mcp_task_registry[task_id]["error"] = str(e)


# --- Task Management Tools (Replaces low-level protocol handlers) ---
@mcp.tool()
def get_task_status(task_id: str) -> str:
    """Check the status of a long-running pipeline task."""
    if task_id not in mcp_task_registry:
        return f"Error: Task {task_id} not found."
    t = mcp_task_registry[task_id]
    return f"Task: {task_id}\nStatus: {t['status']}\nLast Updated: {t['lastUpdatedAt']}"

@mcp.tool()
def get_task_result(task_id: str) -> str:
    """Retrieve the result of a completed pipeline task."""
    if task_id not in mcp_task_registry:
        return f"Error: Task {task_id} not found."
    
    t = mcp_task_registry[task_id]
    if t["status"] == "working":
        return "Task is still working. Please wait."
    elif t["status"] == "failed":
        return f"Task failed with error: {t.get('error', 'Unknown error')}"
    elif t["status"] == "cancelled":
        return "Task was cancelled."
    
    return t["final_result"]

@mcp.tool()
def cancel_task(task_id: str) -> str:
    """Cancel a running pipeline task."""
    if task_id not in mcp_task_registry:
        return f"Error: Task {task_id} not found."
    
    t = mcp_task_registry[task_id]
    if t["status"] in ["completed", "failed", "cancelled"]:
         return f"Cannot cancel task. Current status is already: {t['status']}"
    
    t["status"] = "cancelled"
    t["lastUpdatedAt"] = get_iso_time()
    return f"Task {task_id} successfully cancelled."


# --- Standard Agent Tools ---
@mcp.tool()
def tool_get_csv_catalog() -> str: return get_csv_catalog()

@mcp.tool()
def tool_list_html_files() -> str: return list_html_files()

@mcp.tool()
def tool_get_csv_segment(filename: str, start_row: int, num_rows: int, columns: str) -> str:
    return get_csv_segment(filename, start_row, num_rows, columns)


# --- Task-Augmented Agent Tools ---
def spawn_task(func_name: str, func, *args, **kwargs) -> str:
    task_id = str(uuid.uuid4())
    now = get_iso_time()
    mcp_task_registry[task_id] = {"status": "working", "createdAt": now, "lastUpdatedAt": now}
    
    threading.Thread(target=run_mcp_thread, args=(task_id, func_name, func) + args, kwargs=kwargs).start()
    
    return f"Task started successfully. Task ID: {task_id}. Use the get_task_status tool to check progress."

@mcp.tool()
def trigger_embed_task(file_path: str, text_column: str = "abstract", embedding_column: str = "abstract_embedding", model: str = "allenai/specter2_base") -> str: return spawn_task("embed", add_embeddings_in_place, file_path, text_column, embedding_column, model)

@mcp.tool()
def trigger_umap_task(file_path: str, output_column: str, n_components: int, embedding_column: str = "abstract_embedding") -> str: return spawn_task("umap", reduce_embeddings_with_umap, file_path, embedding_column, output_column, n_components=n_components)

@mcp.tool()
def trigger_cluster_task(file_path: str, coordinate_column: str = "5d", output_column: str = "topic_id") -> str: return spawn_task("cluster", cluster_with_hdbscan, file_path, coordinate_column, output_column)

@mcp.tool()
def trigger_distance_map_task(file_path: str, topic_column: str = "topic_id", text_column: str = "abstract", coordinate_column: str = "2d") -> str: return spawn_task("distance_map", generate_intertopic_distance_map, file_path, topic_column, text_column, coordinate_column)

@mcp.tool()
def trigger_keyword_search_task(file_path: str, query: str, text_column: str = "abstract", new_column_name: str = "kw") -> str: return spawn_task("keyword_search", keyword_search, file_path, query, text_column, new_column_name)

@mcp.tool()
def trigger_semantic_search_task(file_path: str, query: str, embedding_column: str = "abstract_embedding", new_column_name: str = "sem") -> str: return spawn_task("semantic_search", semantic_search, file_path, query, embedding_column, new_column_name)

@mcp.tool()
def trigger_hybrid_search_task(file_path: str, keyword_col: str = "kw", semantic_col: str = "sem", new_column_name: str = "hybrid") -> str: return spawn_task("hybrid_search", hybrid_search, file_path, keyword_col, semantic_col, new_column_name)

@mcp.tool()
def trigger_numerical_distillation_task(file_path: str, output_csv: str = "Filtered_Output.csv", target_score_column: str = "hybrid", threshold: float = 0.70) -> str: return spawn_task("numerical_search", numerical_search, file_path, output_csv, target_score_column, threshold)