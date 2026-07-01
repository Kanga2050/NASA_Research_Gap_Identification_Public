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
from Backend.Annotation_Functions.Embed_Text import embed_text as _embed_text
from Backend.Annotation_Functions.Reduce_Dimensionality import reduce_dimensionality as _reduce_dimensionality
from Backend.Annotation_Functions.Cluster import cluster as _cluster
from Backend.Visualization_Functions.Distance_Map import distance_map as _distance_map
from Backend.Annotation_Functions.Keyword_Score import keyword_score as _keyword_score
from Backend.Annotation_Functions.Semantic_Score import semantic_score as _semantic_score
from Backend.Annotation_Functions.Hybrid_Score import hybrid_score as _hybrid_score
from Backend.Distillation_Functions.Numerical_Filter import numerical_filter as _numerical_filter
from Servers.Getter_Functions.List_Html_Files import list_html_files as _list_html_files
from Servers.Getter_Functions.Get_Csv_Catalog import get_csv_catalog as _get_csv_catalog
from Servers.Getter_Functions.Get_Csv_Segment import get_csv_segment as _get_csv_segment
from Backend.Import_Data.OpenAlex_Scraper import openalex_scraper as _openalex_scraper

app = FastAPI(title="Deconstructed Pipeline API")

# --- Pydantic Models ---
class EmbedTextRequest(BaseModel): csv_name: str; text_column: str = "abstract"; embedding_column: str = "abstract_embedding"; model: str = "allenai/specter2_base"
class ReduceDimensionalityRequest(BaseModel): csv_name: str; embedding_column: str = "abstract_embedding"; output_column: str; n_components: int
class ClusterRequest(BaseModel): csv_name: str; coordinate_column: str = "5d"; output_column: str = "topic_id"; min_cluster_size: int = 32; min_samples: int = 8
class DistanceMapRequest(BaseModel): csv_name: str; topic_column: str = "topic_id"; text_column: str = "abstract"; coordinate_column: str = "2d"; output_name: str = "Space_Biology_Topics"
class KeywordScoreRequest(BaseModel): csv_name: str; query: str; text_column: str = "abstract"; new_column_name: str = "kw"
class SemanticScoreRequest(BaseModel): csv_name: str; query: str; embedding_column: str = "abstract_embedding"; new_column_name: str = "sem"
class HybridScoreRequest(BaseModel): csv_name: str; keyword_col: str = "kw"; semantic_col: str = "sem"; new_column_name: str = "hybrid"
class NumericalFilterRequest(BaseModel): csv_name: str; output_csv: str = "Filtered_Output.csv"; target_score_column: str = "hybrid"; threshold: float = 0.70
class OpenAlexScraperRequest(BaseModel): topic: str; csv_name: str = "scraped"; limit: int = 100000

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

@app.get("/api/catalog/get-csv-catalog")
def get_csv_catalog(): 
    return _get_csv_catalog()

@app.get("/api/catalog/list-html-files")
def list_html_files(): 
    return _list_html_files()

@app.get("/api/data/get-csv-segment")
def get_csv_segment(csv_name: str, start_row: int, num_rows: int, columns: str):
    return _get_csv_segment(csv_name, start_row, num_rows, columns)

@app.post("/api/pipeline/embed_text")
def embed_text(data: EmbedTextRequest, bg_tasks: BackgroundTasks): 
    return queue_rest_task(bg_tasks, "embed_text", _embed_text, data.csv_name, data.text_column, data.embedding_column, data.model)

@app.post("/api/pipeline/reduce-dimensionality")
def reduce_dimensionality(data: ReduceDimensionalityRequest, bg_tasks: BackgroundTasks): 
    return queue_rest_task(bg_tasks, "reduce_dimensionality", _reduce_dimensionality, data.csv_name, data.embedding_column, data.output_column, n_components=data.n_components)

@app.post("/api/pipeline/cluster")
def cluster(data: ClusterRequest, bg_tasks: BackgroundTasks): 
    return queue_rest_task(bg_tasks, "cluster", _cluster, data.csv_name, data.coordinate_column, data.output_column, data.min_cluster_size, data.min_samples)

@app.post("/api/pipeline/distance-map")
def generate_intertopic_distance_map(data: DistanceMapRequest, bg_tasks: BackgroundTasks): 
    return queue_rest_task(bg_tasks, "distance_map", _distance_map, data.csv_name, data.topic_column, data.text_column, data.coordinate_column, data.output_name)

@app.post("/api/pipeline/keyword-score")
def keyword_score(data: KeywordScoreRequest, bg_tasks: BackgroundTasks): 
    return queue_rest_task(bg_tasks, "keyword_score", _keyword_score, data.csv_name, data.query, data.text_column, data.new_column_name)

@app.post("/api/pipeline/semantic-score")
def semantic_score(data: SemanticScoreRequest, bg_tasks: BackgroundTasks): 
    return queue_rest_task(bg_tasks, "semantic_score", _semantic_score, data.csv_name, data.query, data.embedding_column, data.new_column_name)

@app.post("/api/pipeline/hybrid-score")
def hybrid_score(data: HybridScoreRequest, bg_tasks: BackgroundTasks): 
    return queue_rest_task(bg_tasks, "hybrid_score", _hybrid_score, data.csv_name, data.keyword_col, data.semantic_col, data.new_column_name)

@app.post("/api/pipeline/numerical-filter")
def numerical_filter(data: NumericalFilterRequest, bg_tasks: BackgroundTasks): 
    return queue_rest_task(bg_tasks, "numerical_filter", _numerical_filter, data.source_csv, data.output_csv, data.target_score_column, data.threshold)

@app.post("/api/pipeline/fetch-data")
def trigger_fetch_data(data: OpenAlexScraperRequest, bg_tasks: BackgroundTasks): 
    return queue_rest_task(bg_tasks, "openalex_scraper", _openalex_scraper, data.topic, csv_name=data.csv_name, limit=data.limit)