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


# ---- Distillation ----
class CategoricalFilterRequest(BaseModel):
    source_csv: str
    output_csv: str = "Filtered_Output"
    target_column: str
    expected_value: str


class CombineCsvsRequest(BaseModel):
    source_csvs: str  # comma-separated CSV names
    output_csv: str = "Combined_Corpus"
    source_column: str = "source"


class AggregateDictionaryRequest(BaseModel):
    source_csv: str
    output_csv: str = "Aggregated_Counts"
    dict_column: str = "word_freq"


class GroupAggregateRequest(BaseModel):
    source_csv: str
    output_csv: str = "Grouped_Output"
    group_column: str
    value_column: str = ""
    agg: str = "count"
    exclude: str = ""


class TopNByColumnRequest(BaseModel):
    source_csv: str
    output_csv: str = "Top_N_Output"
    sort_column: str
    n: int = 100
    ascending: bool = False


class DeduplicateRequest(BaseModel):
    source_csv: str
    output_csv: str = "Deduplicated_Output"
    subset_column: str


class SelectColumnsRequest(BaseModel):
    source_csv: str
    output_csv: str = "Selected_Columns_Output"
    columns: str  # comma-separated
    drop: bool = False


class CrossTabRequest(BaseModel):
    source_csv: str
    output_csv: str = "Cross_Tab_Output"
    row_column: str
    column_column: str


class ArithmeticRequest(BaseModel):
    source_csv: str
    output_csv: str = "Arithmetic_Output"
    column_a: str
    operation: str = "divide"
    operand: str
    new_column: str = "result"
    group_by: str = ""


# ---- Annotation ----
class WordFrequencyRequest(BaseModel):
    csv_name: str
    text_column: str = "abstract"
    new_column_name: str = "word_freq"
    ngram: int = 1


class LabelTopicsRequest(BaseModel):
    csv_name: str
    topic_column: str = "topic_id"
    text_column: str = "abstract"
    new_column_name: str = "Topic_Label"
    top_n: int = 3


class TextLengthRequest(BaseModel):
    csv_name: str
    text_column: str = "abstract"
    new_column_name: str = "length"
    unit: str = "words"


class ExtractYearRequest(BaseModel):
    csv_name: str
    date_column: str = "publish_time"
    new_column_name: str = "year"


class ToDateRequest(BaseModel):
    csv_name: str
    date_column: str = "publish_time"
    new_column_name: str = "date"


class NormalizeColumnRequest(BaseModel):
    csv_name: str
    value_column: str
    new_column_name: str = ""


# ---- Visualization ----
class BarChartRequest(BaseModel):
    csv_name: str
    category_column: str
    value_column: str = ""
    series_column: str = ""
    title: str = ""
    output_name: str = "bar_chart"
    top_n: int = 25
    exclude: str = ""


class ScatterPlotRequest(BaseModel):
    csv_name: str
    x_column: str = ""
    y_column: str = ""
    color_column: str = ""
    size_column: str = ""
    coord_column: str = ""
    title: str = ""
    output_name: str = "scatter_plot"


class HistogramRequest(BaseModel):
    csv_name: str
    value_column: str
    bins: int = 30
    title: str = ""
    output_name: str = "histogram"
    color_column: str = ""
    log_x: bool = False
    log_y: bool = False


class LineChartRequest(BaseModel):
    csv_name: str
    x_column: str
    y_column: str
    color_column: str = ""
    title: str = ""
    output_name: str = "line_chart"


class BoxPlotRequest(BaseModel):
    csv_name: str
    value_column: str
    category_column: str = ""
    title: str = ""
    output_name: str = "box_plot"
    exclude: str = ""
    log_y: bool = False


class HeatmapRequest(BaseModel):
    csv_name: str
    x_column: str
    y_column: str
    value_column: str = ""
    title: str = ""
    output_name: str = "heatmap"


class PieChartRequest(BaseModel):
    csv_name: str
    category_column: str
    value_column: str = ""
    title: str = ""
    output_name: str = "pie_chart"
    top_n: int = 10
    exclude: str = ""


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


# ---- Distillation ----
@app.post("/api/pipeline/categorical-filter")
def categorical_filter(data: CategoricalFilterRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "categorical_filter", data.source_csv, data.output_csv, data.target_column, data.expected_value, csv_root=str(user_csv_root(user)))


@app.post("/api/pipeline/combine-csvs")
def combine_csvs(data: CombineCsvsRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "combine_csvs", data.source_csvs, data.output_csv, data.source_column, csv_root=str(user_csv_root(user)))


@app.post("/api/pipeline/aggregate-dictionary")
def aggregate_dictionary(data: AggregateDictionaryRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "aggregate_dictionary", data.source_csv, data.output_csv, data.dict_column, csv_root=str(user_csv_root(user)))


@app.post("/api/pipeline/group-aggregate")
def group_aggregate(data: GroupAggregateRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "group_aggregate", data.source_csv, data.output_csv, data.group_column, data.value_column, data.agg, data.exclude, csv_root=str(user_csv_root(user)))


@app.post("/api/pipeline/top-n-by-column")
def top_n_by_column(data: TopNByColumnRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "top_n_by_column", data.source_csv, data.output_csv, data.sort_column, data.n, data.ascending, csv_root=str(user_csv_root(user)))


@app.post("/api/pipeline/deduplicate")
def deduplicate(data: DeduplicateRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "deduplicate", data.source_csv, data.output_csv, data.subset_column, csv_root=str(user_csv_root(user)))


@app.post("/api/pipeline/select-columns")
def select_columns(data: SelectColumnsRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "select_columns", data.source_csv, data.output_csv, data.columns, data.drop, csv_root=str(user_csv_root(user)))


@app.post("/api/pipeline/cross-tab")
def cross_tab(data: CrossTabRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "cross_tab", data.source_csv, data.output_csv, data.row_column, data.column_column, csv_root=str(user_csv_root(user)))


@app.post("/api/pipeline/arithmetic")
def arithmetic(data: ArithmeticRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "arithmetic", data.source_csv, data.output_csv, data.column_a, data.operation, data.operand, data.new_column, data.group_by, csv_root=str(user_csv_root(user)))


# ---- Annotation ----
@app.post("/api/pipeline/word-frequency")
def word_frequency(data: WordFrequencyRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "word_frequency", data.csv_name, data.text_column, data.new_column_name, data.ngram, csv_root=str(user_csv_root(user)))


@app.post("/api/pipeline/label-topics")
def label_topics(data: LabelTopicsRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "label_topics", data.csv_name, data.topic_column, data.text_column, data.new_column_name, data.top_n, csv_root=str(user_csv_root(user)))


@app.post("/api/pipeline/text-length")
def text_length(data: TextLengthRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "text_length", data.csv_name, data.text_column, data.new_column_name, data.unit, csv_root=str(user_csv_root(user)))


@app.post("/api/pipeline/extract-year")
def extract_year(data: ExtractYearRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "extract_year", data.csv_name, data.date_column, data.new_column_name, csv_root=str(user_csv_root(user)))


@app.post("/api/pipeline/to-date")
def to_date(data: ToDateRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "to_date", data.csv_name, data.date_column, data.new_column_name, csv_root=str(user_csv_root(user)))


@app.post("/api/pipeline/normalize-column")
def normalize_column(data: NormalizeColumnRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "normalize_column", data.csv_name, data.value_column, data.new_column_name, csv_root=str(user_csv_root(user)))


# ---- Visualization ----
@app.post("/api/pipeline/bar-chart")
def bar_chart(data: BarChartRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "bar_chart", data.csv_name, data.category_column, data.value_column, data.series_column, data.title, data.output_name, data.top_n, data.exclude, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@app.post("/api/pipeline/scatter-plot")
def scatter_plot(data: ScatterPlotRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "scatter_plot", data.csv_name, data.x_column, data.y_column, data.color_column, data.size_column, data.coord_column, data.title, data.output_name, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@app.post("/api/pipeline/histogram")
def histogram(data: HistogramRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "histogram", data.csv_name, data.value_column, data.bins, data.title, data.output_name, data.color_column, data.log_x, data.log_y, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@app.post("/api/pipeline/line-chart")
def line_chart(data: LineChartRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "line_chart", data.csv_name, data.x_column, data.y_column, data.color_column, data.title, data.output_name, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@app.post("/api/pipeline/box-plot")
def box_plot(data: BoxPlotRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "box_plot", data.csv_name, data.value_column, data.category_column, data.title, data.output_name, data.exclude, data.log_y, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@app.post("/api/pipeline/heatmap")
def heatmap(data: HeatmapRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "heatmap", data.csv_name, data.x_column, data.y_column, data.value_column, data.title, data.output_name, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@app.post("/api/pipeline/pie-chart")
def pie_chart(data: PieChartRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    user = _get_user(x_api_key)
    return _queue(user, "pie_chart", data.csv_name, data.category_column, data.value_column, data.title, data.output_name, data.top_n, data.exclude, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))
