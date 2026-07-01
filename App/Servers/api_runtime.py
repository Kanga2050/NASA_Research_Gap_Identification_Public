import os
import sys

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

current_dir = os.path.dirname(os.path.abspath(__file__))
target_path = os.path.abspath(os.path.join(current_dir, ".."))
if target_path not in sys.path:
    sys.path.append(target_path)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "App.Frontend.webapp.settings")

import django

django.setup()

from App.Frontend.portal.services import resolve_api_key
from App.Frontend.portal.task_engine import get_task_status, queue_user_task
from App.Frontend.webapp.storage import user_csv_root, user_html_root

from Servers.Getter_Functions.Get_Csv_Catalog import get_csv_catalog as _get_csv_catalog
from Servers.Getter_Functions.Get_Csv_Segment import get_csv_segment as _get_csv_segment
from Servers.Getter_Functions.List_Html_Files import list_html_files as _list_html_files

app = FastAPI(title="Deconstructed Pipeline API")


class EmbedTextRequest(BaseModel):
    csv_name: str
    text_column: str = "abstract"
    embedding_column: str = "abstract_embedding"
    model: str = "allenai/specter2_base"


class ReduceDimensionalityRequest(BaseModel):
    csv_name: str
    embedding_column: str = "abstract_embedding"
    output_column: str
    n_components: int


class ClusterRequest(BaseModel):
    csv_name: str
    coordinate_column: str = "5d"
    output_column: str = "topic_id"
    min_cluster_size: int = 32
    min_samples: int = 8


class DistanceMapRequest(BaseModel):
    csv_name: str
    topic_column: str = "topic_id"
    text_column: str = "abstract"
    coordinate_column: str = "2d"
    output_name: str = "Space_Biology_Topics"


class KeywordScoreRequest(BaseModel):
    csv_name: str
    query: str
    text_column: str = "abstract"
    new_column_name: str = "kw"


class SemanticScoreRequest(BaseModel):
    csv_name: str
    query: str
    embedding_column: str = "abstract_embedding"
    new_column_name: str = "sem"


class HybridScoreRequest(BaseModel):
    csv_name: str
    keyword_col: str = "kw"
    semantic_col: str = "sem"
    new_column_name: str = "hybrid"


class NumericalFilterRequest(BaseModel):
    csv_name: str
    output_csv: str = "Filtered_Output"
    target_score_column: str = "hybrid"
    threshold: float = 0.70


class OpenAlexScraperRequest(BaseModel):
    topic: str
    csv_name: str = "scraped"
    limit: int = 10000


def _get_user(x_api_key: str | None):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header.")
    api_key = resolve_api_key(x_api_key)
    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return api_key.user


def _queue(user, function_name: str, *args, **kwargs):
    return queue_user_task(user, function_name, *args, **kwargs)


@app.get("/api/task/status/{task_id}")
def api_get_task_status(task_id: str, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    status = get_task_status(task_id, user=user)
    if status.get("error"):
        raise HTTPException(status_code=404, detail=status["error"])
    return status


@app.get("/api/catalog/get-csv-catalog")
def get_csv_catalog(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _get_csv_catalog(user_csv_root(user))


@app.get("/api/catalog/list-html-files")
def list_html_files(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _list_html_files(user_html_root(user))


@app.get("/api/data/get-csv-segment")
def get_csv_segment(csv_name: str, start_row: int, num_rows: int, columns: str, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _get_csv_segment(csv_name, start_row, num_rows, columns, user_csv_root(user))


@app.post("/api/pipeline/embed_text")
def embed_text(data: EmbedTextRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "embed_text", data.csv_name, data.text_column, data.embedding_column, data.model, csv_root=str(user_csv_root(user)))


@app.post("/api/pipeline/reduce-dimensionality")
def reduce_dimensionality(data: ReduceDimensionalityRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "reduce_dimensionality", data.csv_name, data.embedding_column, data.output_column, data.n_components, csv_root=str(user_csv_root(user)))


@app.post("/api/pipeline/cluster")
def cluster(data: ClusterRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "cluster", data.csv_name, data.coordinate_column, data.output_column, data.min_cluster_size, data.min_samples, csv_root=str(user_csv_root(user)))


@app.post("/api/pipeline/distance-map")
def generate_intertopic_distance_map(data: DistanceMapRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "distance_map", data.csv_name, data.topic_column, data.text_column, data.coordinate_column, data.output_name, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@app.post("/api/pipeline/keyword-score")
def keyword_score(data: KeywordScoreRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "keyword_score", data.csv_name, data.query, data.text_column, data.new_column_name, csv_root=str(user_csv_root(user)))


@app.post("/api/pipeline/semantic-score")
def semantic_score(data: SemanticScoreRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "semantic_score", data.csv_name, data.query, data.embedding_column, data.new_column_name, csv_root=str(user_csv_root(user)))


@app.post("/api/pipeline/hybrid-score")
def hybrid_score(data: HybridScoreRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "hybrid_score", data.csv_name, data.keyword_col, data.semantic_col, data.new_column_name, csv_root=str(user_csv_root(user)))


@app.post("/api/pipeline/numerical-filter")
def numerical_filter(data: NumericalFilterRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "numerical_filter", data.csv_name, data.output_csv, data.target_score_column, data.threshold, csv_root=str(user_csv_root(user)))


@app.post("/api/pipeline/fetch-data")
def trigger_fetch_data(data: OpenAlexScraperRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "openalex_scraper", data.topic, data.csv_name, data.limit, csv_root=str(user_csv_root(user)))
