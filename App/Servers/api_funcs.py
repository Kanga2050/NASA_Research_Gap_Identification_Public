import sys
import os
import uuid
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel

current_dir = os.path.dirname(os.path.abspath(__file__))
target_path = os.path.abspath(os.path.join(current_dir, ".."))
if target_path not in sys.path:
    sys.path.append(target_path)

# Import the shared state manager and the queue helper
from task_manager import shared_task_registry, add_task_to_queue, get_iso_time

# Import all modules and alias them with an underscore to prevent namespace collisions
from Backend.Annotation_Functions.Embedder import add_embeddings_in_place as _add_embeddings_in_place
from Backend.Annotation_Functions.Dimensionality_Reducer import reduce_embeddings_with_umap as _reduce_embeddings_with_umap
from Backend.Annotation_Functions.Clustering import cluster_with_hdbscan as _cluster_with_hdbscan
from Backend.Visualization_Functions.Distance_Map import generate_intertopic_distance_map as _generate_intertopic_distance_map
from Backend.Annotation_Functions.Keyword_Score import keyword_search as _keyword_search
from Backend.Annotation_Functions.Semantic_Score import semantic_search as _semantic_search
from Backend.Annotation_Functions.Hybrid_Score import hybrid_search as _hybrid_search
from Backend.Distillation_Functions.Numerical_Filtering import numerical_search as _numerical_search
from Servers.Getter_Functions.list_html_files import list_html_files as _list_html_files
from Servers.Getter_Functions.get_csv_catalog import get_csv_catalog as _get_csv_catalog
from Servers.Getter_Functions.get_csv_segment import get_csv_segment as _get_csv_segment
from Backend.Import_Data.Scraper import fetch_data as _fetch_data

app = FastAPI(title="Deconstructed Pipeline API")

# --- Pydantic Models ---
class EmbedRequest(BaseModel): file_path: str; text_column: str = "abstract"; embedding_column: str = "abstract_embedding"; model: str = "allenai/specter2_base"
class UmapRequest(BaseModel): file_path: str; embedding_column: str = "abstract_embedding"; output_column: str; n_components: int
class ClusterRequest(BaseModel): file_path: str; coordinate_column: str = "5d"; output_column: str = "topic_id"; min_cluster_size: int = 32; min_samples: int = 8
class DistanceMapRequest(BaseModel): file_path: str; topic_column: str = "topic_id"; text_column: str = "abstract"; coordinate_column: str = "2d"
class KeywordSearchRequest(BaseModel): file_path: str; query: str; text_column: str = "abstract"; new_column_name: str = "kw"
class SemanticSearchRequest(BaseModel): file_path: str; query: str; embedding_column: str = "abstract_embedding"; new_column_name: str = "sem"
class HybridSearchRequest(BaseModel): file_path: str; keyword_col: str = "kw"; semantic_col: str = "sem"; new_column_name: str = "hybrid"
class NumericalSearchRequest(BaseModel): file_path: str; output_csv: str = "Filtered_Output.csv"; target_score_column: str = "hybrid"; threshold: float = 0.70
class FetchDataRequest(BaseModel): topic: str; output_filename: str = "scraped.csv"; limit: int = 100000

def queue_rest_task(bg_tasks, func_name, func, *args, **kwargs):
    task_id = str(uuid.uuid4())
    now = get_iso_time()
    shared_task_registry[task_id] = {"status": "queued", "createdAt": now, "lastUpdatedAt": now}
    bg_tasks.add_task(add_task_to_queue, task_id, func_name, func, *args, **kwargs)
    return {"task_id": task_id, "status": "queued"}


@app.get("/api/task/status/{task_id}")
def api_get_task_status(task_id: str):
    if task_id not in shared_task_registry:
        raise HTTPException(status_code=404, detail="Task not found.")
    return shared_task_registry[task_id]

@app.get("/api/catalog/csv")
def get_csv_catalog(): 
    return _get_csv_catalog()

@app.get("/api/catalog/html")
def list_html_files(): 
    return _list_html_files()

@app.get("/api/data/csv-segment")
def get_csv_segment(filename: str, start_row: int, num_rows: int, columns: str):
    return _get_csv_segment(filename, start_row, num_rows, columns)

@app.post("/api/pipeline/embed")
def add_embeddings_in_place(data: EmbedRequest, bg_tasks: BackgroundTasks): 
    return queue_rest_task(bg_tasks, "embed", _add_embeddings_in_place, data.file_path, data.text_column, data.embedding_column, data.model)

@app.post("/api/pipeline/umap")
def reduce_embeddings_with_umap(data: UmapRequest, bg_tasks: BackgroundTasks): 
    return queue_rest_task(bg_tasks, "umap", _reduce_embeddings_with_umap, data.file_path, data.embedding_column, data.output_column, n_components=data.n_components)

@app.post("/api/pipeline/cluster")
def cluster_with_hdbscan(data: ClusterRequest, bg_tasks: BackgroundTasks): 
    return queue_rest_task(bg_tasks, "cluster", _cluster_with_hdbscan, data.file_path, data.coordinate_column, data.output_column, data.min_cluster_size, data.min_samples)

@app.post("/api/pipeline/distance-map")
def generate_intertopic_distance_map(data: DistanceMapRequest, bg_tasks: BackgroundTasks): 
    return queue_rest_task(bg_tasks, "distance_map", _generate_intertopic_distance_map, data.file_path, data.topic_column, data.text_column, data.coordinate_column)

@app.post("/api/pipeline/keyword-search")
def keyword_search(data: KeywordSearchRequest, bg_tasks: BackgroundTasks): 
    return queue_rest_task(bg_tasks, "keyword_search", _keyword_search, data.file_path, data.query, data.text_column, data.new_column_name)

@app.post("/api/pipeline/semantic-search")
def semantic_search(data: SemanticSearchRequest, bg_tasks: BackgroundTasks): 
    return queue_rest_task(bg_tasks, "semantic_search", _semantic_search, data.file_path, data.query, data.embedding_column, data.new_column_name)

@app.post("/api/pipeline/hybrid-search")
def hybrid_search(data: HybridSearchRequest, bg_tasks: BackgroundTasks): 
    return queue_rest_task(bg_tasks, "hybrid_search", _hybrid_search, data.file_path, data.keyword_col, data.semantic_col, data.new_column_name)

@app.post("/api/pipeline/numerical-distillation")
def numerical_search(data: NumericalSearchRequest, bg_tasks: BackgroundTasks): 
    return queue_rest_task(bg_tasks, "numerical_search", _numerical_search, data.file_path, data.output_csv, data.target_score_column, data.threshold)

@app.post("/api/pipeline/fetch-data")
def trigger_fetch_data(data: FetchDataRequest, bg_tasks: BackgroundTasks): 
    return queue_rest_task(bg_tasks, "fetch_data", _fetch_data, data.topic, output_filename=data.output_filename, limit=data.limit)