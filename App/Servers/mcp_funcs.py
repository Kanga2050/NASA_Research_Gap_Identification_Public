import sys
import os
import uuid
import threading
from fastmcp import FastMCP

current_dir = os.path.dirname(os.path.abspath(__file__))
target_path = os.path.abspath(os.path.join(current_dir, ".."))
if target_path not in sys.path:
    sys.path.append(target_path)

# Import the shared state manager and the queue helper
from task_manager import shared_task_registry, add_task_to_queue, get_iso_time

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
from Backend.Import_Data.Scraper import fetch_data as _fetch_data

# Initialize the MCP Server
mcp = FastMCP("Deconstructed Pipeline")

# --- Helper Function for Background Queueing ---
def queue_mcp_task(func_name: str, func, *args, **kwargs) -> dict:
    """
    Replaces FastAPI's BackgroundTasks by spinning up a lightweight 
    background thread to pass the task into the sequential queue.
    """
    task_id = str(uuid.uuid4())
    now = get_iso_time()
    shared_task_registry[task_id] = {"status": "queued", "createdAt": now, "lastUpdatedAt": now}
    
    # Hand off task insertion to a background thread
    threading.Thread(
        target=add_task_to_queue, 
        args=(task_id, func_name, func, *args), 
        kwargs=kwargs,
        daemon=True
    ).start()
    
    return {"task_id": task_id, "status": "queued"}


# --- Synchronous Getter Tools ---

@mcp.tool()
def api_get_task_status(task_id: str) -> dict:
    """Check the status of a queued or running task by its ID."""
    if task_id not in shared_task_registry:
        return {"error": "Task not found."}
    return shared_task_registry[task_id]

@mcp.tool()
def api_get_csv_catalog():
    """Get the CSV catalog."""
    return get_csv_catalog()

@mcp.tool()
def api_list_html_files():
    """List available HTML files."""
    return list_html_files()

@mcp.tool()
def api_get_csv_segment(filename: str, start_row: int, num_rows: int, columns: str):
    """Retrieve a specific segment of a CSV file."""
    return get_csv_segment(filename, start_row, num_rows, columns)


# --- Asynchronous Pipeline Tools (Method 2) ---

@mcp.tool(name="add_embeddings_in_place")
def trigger_embed(file_path: str, text_column: str = "abstract", embedding_column: str = "abstract_embedding", model: str = "allenai/specter2_base") -> dict:
    """Queue an embedding task."""
    return queue_mcp_task("embed", add_embeddings_in_place, file_path, text_column, embedding_column, model)

@mcp.tool(name="reduce_embeddings_with_umap")
def trigger_umap(file_path: str, output_column: str, n_components: int, embedding_column: str = "abstract_embedding") -> dict:
    """Queue a UMAP dimensionality reduction task."""
    return queue_mcp_task("umap", reduce_embeddings_with_umap, file_path, embedding_column, output_column, n_components=n_components)

@mcp.tool(name="cluster_with_hdbscan")
def trigger_cluster(file_path: str, coordinate_column: str = "5d", output_column: str = "topic_id", min_cluster_size: int = 32, min_samples: int = 8) -> dict:
    """Queue an HDBSCAN clustering task."""
    return queue_mcp_task("cluster", cluster_with_hdbscan, file_path, coordinate_column, output_column, min_cluster_size, min_samples)

@mcp.tool(name="generate_intertopic_distance_map")
def trigger_distance_map(file_path: str, topic_column: str = "topic_id", text_column: str = "abstract", coordinate_column: str = "2d") -> dict:
    """Queue a distance map generation task."""
    return queue_mcp_task("distance_map", generate_intertopic_distance_map, file_path, topic_column, text_column, coordinate_column)

@mcp.tool(name="keyword_search")
def trigger_keyword_search(file_path: str, query: str, text_column: str = "abstract", new_column_name: str = "kw") -> dict:
    """Queue a keyword search task."""
    return queue_mcp_task("keyword_search", keyword_search, file_path, query, text_column, new_column_name)

@mcp.tool(name="semantic_search")
def trigger_semantic_search(file_path: str, query: str, embedding_column: str = "abstract_embedding", new_column_name: str = "sem") -> dict:
    """Queue a semantic search task."""
    return queue_mcp_task("semantic_search", semantic_search, file_path, query, embedding_column, new_column_name)

@mcp.tool(name="hybrid_search")
def trigger_hybrid_search(file_path: str, keyword_col: str = "kw", semantic_col: str = "sem", new_column_name: str = "hybrid") -> dict:
    """Queue a hybrid search task combining keyword and semantic scores."""
    return queue_mcp_task("hybrid_search", hybrid_search, file_path, keyword_col, semantic_col, new_column_name)

@mcp.tool(name="numerical_search")
def trigger_numerical_search(file_path: str, output_csv: str = "Filtered_Output.csv", target_score_column: str = "hybrid", threshold: float = 0.70) -> dict:
    """Queue a numerical distillation filtering task."""
    return queue_mcp_task("numerical_search", numerical_search, file_path, output_csv, target_score_column, threshold)

@mcp.tool()
def trigger_fetch_data_task(topic: str, output_filename: str = "scraped.csv", limit: int = 10000) -> str: 
    """Scrapes academic papers from OpenAlex based on a topic and saves them to a CSV."""
    return queue_mcp_task("fetch_data", _fetch_data, topic, output_filename=output_filename, limit=limit)