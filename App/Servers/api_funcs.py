import sys
import os
import uuid
from typing import Dict, Any
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel

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

app = FastAPI(title="Deconstructed Pipeline API")

# --- REST Task Engine ---
rest_task_registry: Dict[str, Any] = {}

def run_rest_task(task_id: str, function_name: str, func, *args, **kwargs):
    """Executes a pipeline step for the REST API."""
    try:
        rest_task_registry[task_id] = {"function": function_name, "status": "processing"}
        print(f"[REST API Engine] Running task {task_id} ({function_name})...")
        func(*args, **kwargs)
        rest_task_registry[task_id]["status"] = "completed"
        rest_task_registry[task_id]["result"] = f"Function '{function_name}' executed successfully."
    except Exception as e:
        rest_task_registry[task_id]["status"] = "failed"
        rest_task_registry[task_id]["error"] = str(e)

# --- Pydantic Models ---
class EmbedRequest(BaseModel): file_path: str; text_column: str = "abstract"; embedding_column: str = "abstract_embedding"; model: str = "allenai/specter2_base"
class UmapRequest(BaseModel): file_path: str; embedding_column: str = "abstract_embedding"; output_column: str; n_components: int
class ClusterRequest(BaseModel): file_path: str; coordinate_column: str = "5d"; output_column: str = "topic_id"; min_cluster_size: int = 32; min_samples: int = 8
class DistanceMapRequest(BaseModel): file_path: str; topic_column: str = "topic_id"; text_column: str = "abstract"; coordinate_column: str = "2d"
class KeywordSearchRequest(BaseModel): file_path: str; query: str; text_column: str = "abstract"; new_column_name: str = "kw"
class SemanticSearchRequest(BaseModel): file_path: str; query: str; embedding_column: str = "abstract_embedding"; new_column_name: str = "sem"
class HybridSearchRequest(BaseModel): file_path: str; keyword_col: str = "kw"; semantic_col: str = "sem"; new_column_name: str = "hybrid"
class NumericalSearchRequest(BaseModel): file_path: str; output_csv: str = "Filtered_Output.csv"; target_score_column: str = "hybrid"; threshold: float = 0.70

# --- REST Endpoints ---
@app.get("/api/task/status/{task_id}")
def api_get_task_status(task_id: str):
    if task_id not in rest_task_registry:
        raise HTTPException(status_code=404, detail="Task not found.")
    return rest_task_registry[task_id]

@app.get("/api/catalog/csv")
def api_get_csv_catalog(): return get_csv_catalog()

@app.get("/api/catalog/html")
def api_list_html_files(): return list_html_files()

@app.get("/api/data/csv-segment")
def api_get_csv_segment(filename: str, start_row: int, num_rows: int, columns: str):
    return get_csv_segment(filename, start_row, num_rows, columns)

def queue_rest_task(bg_tasks, func_name, func, *args, **kwargs):
    task_id = str(uuid.uuid4())
    rest_task_registry[task_id] = {"status": "queued"}
    bg_tasks.add_task(run_rest_task, task_id, func_name, func, *args, **kwargs)
    return {"task_id": task_id, "status": "queued"}

@app.post("/api/pipeline/embed")
def trigger_embed(data: EmbedRequest, bg_tasks: BackgroundTasks): return queue_rest_task(bg_tasks, "embed", add_embeddings_in_place, data.file_path, data.text_column, data.embedding_column, data.model)

@app.post("/api/pipeline/umap")
def trigger_umap(data: UmapRequest, bg_tasks: BackgroundTasks): return queue_rest_task(bg_tasks, "umap", reduce_embeddings_with_umap, data.file_path, data.embedding_column, data.output_column, n_components=data.n_components)

@app.post("/api/pipeline/cluster")
def trigger_cluster(data: ClusterRequest, bg_tasks: BackgroundTasks): return queue_rest_task(bg_tasks, "cluster", cluster_with_hdbscan, data.file_path, data.coordinate_column, data.output_column, data.min_cluster_size, data.min_samples)

@app.post("/api/pipeline/distance-map")
def trigger_distance_map(data: DistanceMapRequest, bg_tasks: BackgroundTasks): return queue_rest_task(bg_tasks, "distance_map", generate_intertopic_distance_map, data.file_path, data.topic_column, data.text_column, data.coordinate_column)

@app.post("/api/pipeline/keyword-search")
def trigger_keyword_search(data: KeywordSearchRequest, bg_tasks: BackgroundTasks): return queue_rest_task(bg_tasks, "keyword_search", keyword_search, data.file_path, data.query, data.text_column, data.new_column_name)

@app.post("/api/pipeline/semantic-search")
def trigger_semantic_search(data: SemanticSearchRequest, bg_tasks: BackgroundTasks): return queue_rest_task(bg_tasks, "semantic_search", semantic_search, data.file_path, data.query, data.embedding_column, data.new_column_name)

@app.post("/api/pipeline/hybrid-search")
def trigger_hybrid_search(data: HybridSearchRequest, bg_tasks: BackgroundTasks): return queue_rest_task(bg_tasks, "hybrid_search", hybrid_search, data.file_path, data.keyword_col, data.semantic_col, data.new_column_name)

@app.post("/api/pipeline/numerical-distillation")
def trigger_numerical_search(data: NumericalSearchRequest, bg_tasks: BackgroundTasks): return queue_rest_task(bg_tasks, "numerical_search", numerical_search, data.file_path, data.output_csv, data.target_score_column, data.threshold)