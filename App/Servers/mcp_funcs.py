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
from Backend.Annotation_Functions.Embed_Text import embed_text as _embed_text
from Backend.Annotation_Functions.Reduce_Dimensionality import reduce_dimensionality as _reduce_dimensionality
from Backend.Annotation_Functions.Cluster import cluster as _cluster
from Backend.Visualization_Functions.Distance_Map import distance_map as _distance_map
from Backend.Annotation_Functions.Keyword_Score import keyword_score as _keyword_score
from Backend.Annotation_Functions.Semantic_Score import semantic_score as _semantic_score
from Backend.Annotation_Functions.Hybrid_Score import hybrid_score as _hybrid_score
from Backend.Distillation_Functions.Numerical_Filter import numerical_filter as _numerical_filter

# Import getter functions
from Servers.Getter_Functions.List_Html_Files import list_html_files as _list_html_files
from Servers.Getter_Functions.Get_Csv_Catalog import get_csv_catalog as _get_csv_catalog
from Servers.Getter_Functions.Get_Csv_Segment import get_csv_segment as _get_csv_segment
from Backend.Import_Data.OpenAlex_Scraper import openalex_scraper as _openalex_scraper

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
def get_task_status(task_id: str):
    """Check the status of a queued or running task by its ID."""
    if task_id not in shared_task_registry:
        return {"error": "Task not found."}
    return shared_task_registry[task_id]

@mcp.tool()
def get_csv_catalog():
    """Get the CSV catalog."""
    return _get_csv_catalog()

@mcp.tool()
def list_html_files():
    """List available HTML files."""
    return _list_html_files()

@mcp.tool()
def get_csv_segment(csv_name: str, start_row: int, num_rows: int, columns: str):
    """Retrieve a specific segment of a CSV file."""
    return _get_csv_segment(csv_name, start_row, num_rows, columns)


# --- Asynchronous Pipeline Tools (Method 2) ---

@mcp.tool(name="embed_text")
def embed_text(csv_name: str, text_column: str = "abstract", embedding_column: str = "abstract_embedding", model: str = "allenai/specter2_base") -> dict:
    """Queue an embedding task."""
    return queue_mcp_task("embed_text", _embed_text, csv_name, text_column, embedding_column, model)

@mcp.tool(name="reduce_dimensionality")
def reduce_dimensionality(csv_name: str, output_column: str, n_components: int, embedding_column: str = "abstract_embedding") -> dict:
    """Queue a dimensionality reduction task."""
    return queue_mcp_task("reduce_dimensionality", _reduce_dimensionality, csv_name, embedding_column, output_column, n_components=n_components)

@mcp.tool(name="cluster")
def cluster(csv_name: str, coordinate_column: str = "5d", output_column: str = "topic_id", min_cluster_size: int = 32, min_samples: int = 8) -> dict:
    """Queue an HDBSCAN clustering task."""
    return queue_mcp_task("cluster", _cluster, csv_name, coordinate_column, output_column, min_cluster_size, min_samples)

@mcp.tool(name="distance_map")
def distance_map(csv_name: str, topic_column: str = "topic_id", text_column: str = "abstract", coordinate_column: str = "2d", output_name: str = "Space_Biology_Topics") -> dict:
    """Queue a distance map generation task."""
    return queue_mcp_task("distance_map", _distance_map, csv_name, topic_column, text_column, coordinate_column, output_name)

@mcp.tool(name="keyword_score")
def keyword_score(csv_name: str, query: str, text_column: str = "abstract", new_column_name: str = "kw") -> dict:
    """Queue a keyword score task."""
    return queue_mcp_task("keyword_score", _keyword_score, csv_name, query, text_column, new_column_name)

@mcp.tool(name="semantic_score")
def semantic_score(csv_name: str, query: str, embedding_column: str = "abstract_embedding", new_column_name: str = "sem") -> dict:
    """Queue a semantic score task."""
    return queue_mcp_task("semantic_score", _semantic_score, csv_name, query, embedding_column, new_column_name)

@mcp.tool(name="hybrid_score")
def hybrid_score(csv_name: str, keyword_col: str = "kw", semantic_col: str = "sem", new_column_name: str = "hybrid") -> dict:
    """Queue a hybrid score task combining keyword and semantic scores."""
    return queue_mcp_task("hybrid_score", _hybrid_score, csv_name, keyword_col, semantic_col, new_column_name)

@mcp.tool(name="numerical_filter")
def numerical_filter(source_csv: str, output_csv: str = "Filtered_Output.csv", target_score_column: str = "hybrid", threshold: float = 0.70) -> dict:
    """Queue a numerical distillation filtering task."""
    return queue_mcp_task("numerical_filter", _numerical_filter, source_csv, output_csv, target_score_column, threshold)

@mcp.tool(name="openalex_scraper")
def openalex_scraper(topic: str, csv_name: str = "scraped", limit: int = 10000) -> dict: 
    """Scrapes academic papers from OpenAlex based on a topic and saves them to a CSV."""
    return queue_mcp_task("openalex_scraper", _openalex_scraper, topic, csv_name=csv_name, limit=limit)