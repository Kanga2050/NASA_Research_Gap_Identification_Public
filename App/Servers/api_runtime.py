import os
import sys

from fastapi import Depends, FastAPI, Header, HTTPException
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
from App.Frontend.webapp.storage import user_csv_root, user_html_root, user_pdf_root

from Servers.Getter_Functions.Get_Csv_Catalog import get_csv_catalog as _get_csv_catalog
from Servers.Getter_Functions.Get_Csv_Segment import get_csv_segment as _get_csv_segment
from Servers.Getter_Functions.List_Html_Files import list_html_files as _list_html_files
from Servers.Getter_Functions.List_Pdf_Folders import list_pdf_folders as _list_pdf_folders

app = FastAPI(
    title="Deconstructed Pipeline API",
    description=(
        "Atomic data-science blocks for the research-gap platform. Every pipeline "
        "endpoint authenticates via the `X-API-Key` header, queues a background task "
        "for the calling user, and immediately returns `{task_id, status}`; poll "
        "`GET /api/task/status/{task_id}` (whose `latest_print` field carries the "
        "live progress line) to follow it to completion. Functions fall into four "
        "families: Import (fetch raw data), Annotation (add a column in place), "
        "Distillation (write a new derived CSV) and Visualization (render an HTML "
        "chart)."
    ),
)


class EmbedTextRequest(BaseModel):
    csv_name: str
    text_column: str = "text"
    embedding_column: str = "text_embedding"
    model: str = "allenai/specter2_base"


class ReduceDimensionalityRequest(BaseModel):
    csv_name: str
    embedding_column: str = "text_embedding"
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
    text_column: str = "text"
    coordinate_column: str = "2d"
    output_name: str = "Space_Biology_Topics"


class KeywordScoreRequest(BaseModel):
    csv_name: str
    query: str
    text_column: str = "text"
    new_column_name: str = "kw"


class SemanticScoreRequest(BaseModel):
    csv_name: str
    query: str
    embedding_column: str = "text_embedding"
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


class ChunkPdfsRequest(BaseModel):
    folders: str  # one or more PDF collection names, comma-separated
    csv_name: str = "pdf_chunks"
    source_label: str = ""
    chunk_words: int = 250
    overlap_words: int = 40
    enrich: bool = True


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
    text_column: str = "text"
    new_column_name: str = "word_freq"
    ngram: int = 1


class LabelTopicsRequest(BaseModel):
    csv_name: str
    topic_column: str = "topic_id"
    text_column: str = "text"
    new_column_name: str = "Topic_Label"
    top_n: int = 3


class TextLengthRequest(BaseModel):
    csv_name: str
    text_column: str = "text"
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


class HierarchicalClusterRequest(BaseModel):
    csv_name: str
    topic_column: str = "topic_id"
    embedding_column: str = "5d"
    output_column: str = "hcluster"
    n_clusters: int = 10


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


class HierarchicalDendrogramRequest(BaseModel):
    csv_name: str
    topic_column: str = "topic_id"
    text_column: str = "text"
    embedding_column: str = "5d"
    output_name: str = "Topic_Dendrogram"
    title: str = ""
    top_n: int = 30
    orientation: str = "left"


def _current_user(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header.")
    api_key = resolve_api_key(x_api_key)
    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return api_key.user


def _queue(user, function_name: str, *args, **kwargs):
    return queue_user_task(user, function_name, *args, **kwargs)


CurrentUser = Depends(_current_user)


@app.get(
    "/api/task/status/{task_id}",
    tags=["Tasks"],
    summary="Get the status and live progress of a queued task",
    description=(
        "Return the current state of a background task by its `task_id`: status "
        "(queued/working/completed/failed/cancelled), the function that ran, "
        "timestamps, any error, and `latest_print` -- the most recent progress line "
        "the task emitted. Poll this to follow a pipeline job to completion. 404 if "
        "the task does not exist or belongs to another user."
    ),
)
def api_get_task_status(task_id: str, user=CurrentUser):
    status = get_task_status(task_id, user=user)
    if status.get("error"):
        raise HTTPException(status_code=404, detail=status["error"])
    return status


@app.get(
    "/api/catalog/get-csv-catalog",
    tags=["Catalog"],
    summary="List the caller's CSV datasets",
    description="List every CSV dataset in the caller's workspace with its columns and row count. Call this first to discover available data and exact column names.",
)
def get_csv_catalog(user=CurrentUser):
    return _get_csv_catalog(user_csv_root(user))


@app.get(
    "/api/catalog/list-html-files",
    tags=["Catalog"],
    summary="List the caller's rendered visualizations",
    description="List the rendered visualization HTML files (charts, maps) in the caller's workspace.",
)
def list_html_files(user=CurrentUser):
    return _list_html_files(user_html_root(user))


@app.get(
    "/api/data/get-csv-segment",
    tags=["Catalog"],
    summary="Read a slice of a CSV dataset",
    description="Read `num_rows` rows starting at `start_row` (0-based) from `csv_name`, limited to the comma-separated `columns`. Preview or page through a dataset without loading the whole file.",
)
def get_csv_segment(csv_name: str, start_row: int, num_rows: int, columns: str, user=CurrentUser):
    return _get_csv_segment(csv_name, start_row, num_rows, columns, user_csv_root(user))


@app.post(
    "/api/pipeline/embed_text",
    tags=["Annotation"],
    summary="Embed a text column into semantic vectors",
    description=(
        "[Annotation] Compute a semantic embedding for each row's `text_column` and "
        "store it in `embedding_column`, editing the CSV in place. Foundation for "
        "semantic search, dimensionality reduction and clustering; slow on large "
        "datasets. Queues a background task and returns its task_id."
    ),
)
def embed_text(data: EmbedTextRequest, user=CurrentUser):
    return _queue(user, "embed_text", data.csv_name, data.text_column, data.embedding_column, data.model, csv_root=str(user_csv_root(user)))


@app.post(
    "/api/pipeline/reduce-dimensionality",
    tags=["Annotation"],
    summary="Reduce embeddings to fewer dimensions with UMAP",
    description=(
        "[Annotation] Run UMAP to compress the embeddings in `embedding_column` down "
        "to `n_components` dimensions, written to `output_column`. Use n=2 for a "
        "plottable map, or n=5 as the input to clustering. Queues a background task "
        "and returns its task_id."
    ),
)
def reduce_dimensionality(data: ReduceDimensionalityRequest, user=CurrentUser):
    return _queue(user, "reduce_dimensionality", data.csv_name, data.embedding_column, data.output_column, data.n_components, csv_root=str(user_csv_root(user)))


@app.post(
    "/api/pipeline/cluster",
    tags=["Annotation"],
    summary="Cluster rows into topics with HDBSCAN",
    description=(
        "[Annotation] Group rows into topics with HDBSCAN over `coordinate_column` "
        "(e.g. the 5D UMAP column), writing a topic id per row into `output_column`. "
        "Larger min_cluster_size/min_samples yield fewer, tighter topics; id -1 is "
        "noise. Queues a background task and returns its task_id."
    ),
)
def cluster(data: ClusterRequest, user=CurrentUser):
    return _queue(user, "cluster", data.csv_name, data.coordinate_column, data.output_column, data.min_cluster_size, data.min_samples, csv_root=str(user_csv_root(user)))


@app.post(
    "/api/pipeline/distance-map",
    tags=["Visualization"],
    summary="Render an intertopic distance map",
    description=(
        "[Visualization] Render an intertopic distance map (HTML): one bubble per "
        "topic at its mean 2D coordinate, sized by document count and labelled with "
        "its top keywords. Queues a background task and returns its task_id."
    ),
)
def generate_intertopic_distance_map(data: DistanceMapRequest, user=CurrentUser):
    return _queue(user, "distance_map", data.csv_name, data.topic_column, data.text_column, data.coordinate_column, data.output_name, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@app.post(
    "/api/pipeline/keyword-score",
    tags=["Annotation"],
    summary="Score rows by keyword (TF-IDF) relevance to a query",
    description=(
        "[Annotation] Score every row for lexical relevance to `query` via TF-IDF "
        "cosine similarity over `text_column`, writing a 0-1 score into "
        "`new_column_name`. Rewards exact word overlap. Queues a background task and "
        "returns its task_id."
    ),
)
def keyword_score(data: KeywordScoreRequest, user=CurrentUser):
    return _queue(user, "keyword_score", data.csv_name, data.query, data.text_column, data.new_column_name, csv_root=str(user_csv_root(user)))


@app.post(
    "/api/pipeline/semantic-score",
    tags=["Annotation"],
    summary="Score rows by semantic (meaning) relevance to a query",
    description=(
        "[Annotation] Score every row for meaning-based relevance to `query` by "
        "cosine similarity between the query embedding and each row's stored "
        "`embedding_column`, writing a score into `new_column_name`. Requires "
        "`embed_text` first. Queues a background task and returns its task_id."
    ),
)
def semantic_score(data: SemanticScoreRequest, user=CurrentUser):
    return _queue(user, "semantic_score", data.csv_name, data.query, data.embedding_column, data.new_column_name, csv_root=str(user_csv_root(user)))


@app.post(
    "/api/pipeline/hybrid-score",
    tags=["Annotation"],
    summary="Fuse keyword and semantic scores into one relevance score",
    description=(
        "[Annotation] Fuse a keyword-score column and a semantic-score column into "
        "one combined 0-1 relevance score (Reciprocal Rank Fusion) in "
        "`new_column_name`, balancing exact-match and meaning-based retrieval. Queues "
        "a background task and returns its task_id."
    ),
)
def hybrid_score(data: HybridScoreRequest, user=CurrentUser):
    return _queue(user, "hybrid_score", data.csv_name, data.keyword_col, data.semantic_col, data.new_column_name, csv_root=str(user_csv_root(user)))


@app.post(
    "/api/pipeline/numerical-filter",
    tags=["Distillation"],
    summary="Filter rows above a numeric or date threshold into a new CSV",
    description=(
        "[Distillation] Keep only rows whose `target_score_column` is >= `threshold` "
        "(numeric, or an ISO-8601 date for chronological filtering), writing them "
        "sorted best-first to a new `output_csv`. Queues a background task and returns "
        "its task_id."
    ),
)
def numerical_filter(data: NumericalFilterRequest, user=CurrentUser):
    return _queue(user, "numerical_filter", data.csv_name, data.output_csv, data.target_score_column, data.threshold, csv_root=str(user_csv_root(user)))


@app.post(
    "/api/pipeline/fetch-data",
    tags=["Import"],
    summary="Scrape scholarly works for a topic from OpenAlex",
    description=(
        "[Import] Download up to `limit` scholarly works matching `topic` (that have "
        "an abstract) from the OpenAlex API into a brand-new `csv_name` CSV, with "
        "title, abstract, authors, journal, DOI and publish date. The usual starting "
        "point of a pipeline. Queues a background task and returns its task_id."
    ),
)
def trigger_fetch_data(data: OpenAlexScraperRequest, user=CurrentUser):
    return _queue(user, "openalex_scraper", data.topic, data.csv_name, data.limit, csv_root=str(user_csv_root(user)))


@app.get(
    "/api/catalog/list-pdf-folders",
    tags=["Catalog"],
    summary="List the caller's PDF collections",
    description="List the PDF collection folders the caller can chunk -- their own uploaded folders plus the shared public library. Pass one or more of these names (comma-separated) to /api/pipeline/chunk-pdfs.",
)
def list_pdf_folders(user=CurrentUser):
    return _list_pdf_folders(user_pdf_root(user))


@app.post(
    "/api/pipeline/chunk-pdfs",
    tags=["Import"],
    summary="Chunk one or more PDF collections into a new corpus CSV",
    description=(
        "[Import] Extract text from every PDF in the named `folders` (comma-separated "
        "collection names from your own PDF area or the public library -- see "
        "/api/catalog/list-pdf-folders), split it into sentence-aware chunks (~`chunk_words` "
        "words, ~`overlap_words` overlap, never cutting a sentence), and write one row per "
        "chunk to a brand-new `csv_name` CSV with a `text` column plus provenance "
        "(source_file, source, doi, title, authors, journal, publish_time). `source_label` "
        "tags each row's origin (defaults to the collection name). With `enrich`, OSDR-style "
        "DOI filenames are looked up on Crossref for clean authors/journal/title. Feed the "
        "`text` column through embed_text -> reduce_dimensionality -> cluster -> label_topics "
        "to match Space_Biology's columns. Queues a background task and returns its task_id."
    ),
)
def trigger_chunk_pdfs(data: ChunkPdfsRequest, user=CurrentUser):
    return _queue(user, "chunk_pdfs", data.folders, data.csv_name, data.source_label,
                  data.chunk_words, data.overlap_words, data.enrich,
                  csv_root=str(user_csv_root(user)), pdf_root=str(user_pdf_root(user)))


# ---- Distillation ----
@app.post(
    "/api/pipeline/categorical-filter",
    tags=["Distillation"],
    summary="Keep rows exactly matching a category value",
    description="[Distillation] Keep only rows whose `target_column` exactly equals `expected_value` (compared as text) into a new `output_csv` -- e.g. isolate a single topic. Queues a background task and returns its task_id.",
)
def categorical_filter(data: CategoricalFilterRequest, user=CurrentUser):
    return _queue(user, "categorical_filter", data.source_csv, data.output_csv, data.target_column, data.expected_value, csv_root=str(user_csv_root(user)))


@app.post(
    "/api/pipeline/combine-csvs",
    tags=["Distillation"],
    summary="Stack several CSVs into one, tagged by origin",
    description="[Distillation] Stack the comma-separated `source_csvs` into one CSV, adding `source_column` that tags each row with the file it came from. Queues a background task and returns its task_id.",
)
def combine_csvs(data: CombineCsvsRequest, user=CurrentUser):
    return _queue(user, "combine_csvs", data.source_csvs, data.output_csv, data.source_column, csv_root=str(user_csv_root(user)))


@app.post(
    "/api/pipeline/aggregate-dictionary",
    tags=["Distillation"],
    summary="Sum per-row dictionaries into a corpus-wide table",
    description="[Distillation] Sum the per-row {key: number} dictionaries in `dict_column` across every row into a new [key, sum] CSV sorted by total. Pairs with word_frequency. Queues a background task and returns its task_id.",
)
def aggregate_dictionary(data: AggregateDictionaryRequest, user=CurrentUser):
    return _queue(user, "aggregate_dictionary", data.source_csv, data.output_csv, data.dict_column, csv_root=str(user_csv_root(user)))


@app.post(
    "/api/pipeline/group-aggregate",
    tags=["Distillation"],
    summary="Group rows and aggregate into a summary CSV",
    description="[Distillation] Group by `group_column` (comma-separate for multi-dimensional counts) and aggregate: count rows, or apply mean/sum/min/max to `value_column`. `exclude` drops comma-separated group values (e.g. '-1'). Queues a background task and returns its task_id.",
)
def group_aggregate(data: GroupAggregateRequest, user=CurrentUser):
    return _queue(user, "group_aggregate", data.source_csv, data.output_csv, data.group_column, data.value_column, data.agg, data.exclude, csv_root=str(user_csv_root(user)))


@app.post(
    "/api/pipeline/top-n-by-column",
    tags=["Distillation"],
    summary="Keep the top N rows by a column",
    description="[Distillation] Sort by `sort_column` and keep the top `n` rows into a new CSV (`ascending=true` keeps the smallest). Threshold-free, unlike numerical-filter. Queues a background task and returns its task_id.",
)
def top_n_by_column(data: TopNByColumnRequest, user=CurrentUser):
    return _queue(user, "top_n_by_column", data.source_csv, data.output_csv, data.sort_column, data.n, data.ascending, csv_root=str(user_csv_root(user)))


@app.post(
    "/api/pipeline/deduplicate",
    tags=["Distillation"],
    summary="Drop rows repeating a value in a column",
    description="[Distillation] Drop rows that repeat a value in `subset_column` (keeping the first) into a new CSV -- e.g. dedupe papers by title or doi. Queues a background task and returns its task_id.",
)
def deduplicate(data: DeduplicateRequest, user=CurrentUser):
    return _queue(user, "deduplicate", data.source_csv, data.output_csv, data.subset_column, csv_root=str(user_csv_root(user)))


@app.post(
    "/api/pipeline/select-columns",
    tags=["Distillation"],
    summary="Keep or drop a subset of columns",
    description="[Distillation] Write a new CSV keeping only the comma-separated `columns` (or, with `drop=true`, everything except them). Handy for stripping heavy embedding columns. Queues a background task and returns its task_id.",
)
def select_columns(data: SelectColumnsRequest, user=CurrentUser):
    return _queue(user, "select_columns", data.source_csv, data.output_csv, data.columns, data.drop, csv_root=str(user_csv_root(user)))


@app.post(
    "/api/pipeline/cross-tab",
    tags=["Distillation"],
    summary="Build a contingency count matrix (for a heatmap)",
    description="[Distillation] Count how many rows fall into each (`row_column`, `column_column`) pairing, as a matrix CSV -- the shape a heatmap expects. Queues a background task and returns its task_id.",
)
def cross_tab(data: CrossTabRequest, user=CurrentUser):
    return _queue(user, "cross_tab", data.source_csv, data.output_csv, data.row_column, data.column_column, csv_root=str(user_csv_root(user)))


@app.post(
    "/api/pipeline/arithmetic",
    tags=["Distillation"],
    summary="Compute a new column via column arithmetic",
    description="[Distillation] Write `new_column = column_a <operation> operand` (add/subtract/multiply/divide) to a new CSV, where operand is a column or constant. With `group_by`, a column operand becomes its per-group SUM, so count/count per group gives each row's share (x100 = percent). Queues a background task and returns its task_id.",
)
def arithmetic(data: ArithmeticRequest, user=CurrentUser):
    return _queue(user, "arithmetic", data.source_csv, data.output_csv, data.column_a, data.operation, data.operand, data.new_column, data.group_by, csv_root=str(user_csv_root(user)))


# ---- Annotation ----
@app.post(
    "/api/pipeline/word-frequency",
    tags=["Annotation"],
    summary="Annotate each row with a word-count dictionary",
    description="[Annotation] Annotate each row with its own {word: count} dictionary from `text_column` (lemmatized, stop-word filtered) in `new_column_name`; set `ngram`=2/3 for phrases. Feed to aggregate-dictionary for a corpus table. Queues a background task and returns its task_id.",
)
def word_frequency(data: WordFrequencyRequest, user=CurrentUser):
    return _queue(user, "word_frequency", data.csv_name, data.text_column, data.new_column_name, data.ngram, csv_root=str(user_csv_root(user)))


@app.post(
    "/api/pipeline/label-topics",
    tags=["Annotation"],
    summary="Label each topic with its top keywords",
    description="[Annotation] Add a `new_column_name` (default Topic_Label) mapping each row's topic to that topic's top `top_n` keywords, so charts can group by readable labels instead of raw numbers. Run after cluster. Queues a background task and returns its task_id.",
)
def label_topics(data: LabelTopicsRequest, user=CurrentUser):
    return _queue(user, "label_topics", data.csv_name, data.topic_column, data.text_column, data.new_column_name, data.top_n, csv_root=str(user_csv_root(user)))


@app.post(
    "/api/pipeline/text-length",
    tags=["Annotation"],
    summary="Add a text-length column (words or chars)",
    description="[Annotation] Add a numeric column with the length of `text_column`, measured in `unit`='words' or 'chars'. Queues a background task and returns its task_id.",
)
def text_length(data: TextLengthRequest, user=CurrentUser):
    return _queue(user, "text_length", data.csv_name, data.text_column, data.new_column_name, data.unit, csv_root=str(user_csv_root(user)))


@app.post(
    "/api/pipeline/extract-year",
    tags=["Annotation"],
    summary="Extract a four-digit year from a date column",
    description="[Annotation] Parse a four-digit year out of `date_column` into a new numeric column, unlocking temporal charts (e.g. publications per year). Queues a background task and returns its task_id.",
)
def extract_year(data: ExtractYearRequest, user=CurrentUser):
    return _queue(user, "extract_year", data.csv_name, data.date_column, data.new_column_name, csv_root=str(user_csv_root(user)))


@app.post(
    "/api/pipeline/to-date",
    tags=["Annotation"],
    summary="Normalize a column to ISO-8601 dates",
    description="[Annotation] Normalize `date_column` into a canonical ISO-8601 (YYYY-MM-DD) date column that sorts chronologically and supports date range/threshold filtering and time-axis charts. Queues a background task and returns its task_id.",
)
def to_date(data: ToDateRequest, user=CurrentUser):
    return _queue(user, "to_date", data.csv_name, data.date_column, data.new_column_name, csv_root=str(user_csv_root(user)))


@app.post(
    "/api/pipeline/normalize-column",
    tags=["Annotation"],
    summary="Min-max scale a numeric column to 0-1",
    description="[Annotation] Min-max scale `value_column` into the 0-1 range. A blank/equal `new_column_name` overwrites `value_column` in place; otherwise the scaled values land in a new column. Queues a background task and returns its task_id.",
)
def normalize_column(data: NormalizeColumnRequest, user=CurrentUser):
    return _queue(user, "normalize_column", data.csv_name, data.value_column, data.new_column_name, csv_root=str(user_csv_root(user)))


@app.post(
    "/api/pipeline/hierarchical-cluster",
    tags=["Annotation"],
    summary="Agglomerate topics into hierarchical super-clusters",
    description=(
        "[Annotation] Agglomerate an existing `topic_column` into `n_clusters` broader "
        "hierarchical super-clusters, writing each row's super-cluster id into "
        "`output_column`. Each topic is reduced to the centroid of its members' "
        "`embedding_column` vectors, the centroids are Ward-linked, and the tree is cut "
        "into `n_clusters` groups -- a coarser, top-down complement to HDBSCAN's flat "
        "cluster. Only noise stays -1. Queues a background task and returns its task_id."
    ),
)
def hierarchical_cluster(data: HierarchicalClusterRequest, user=CurrentUser):
    return _queue(user, "hierarchical_cluster", data.csv_name, data.topic_column, data.embedding_column, data.output_column, data.n_clusters, csv_root=str(user_csv_root(user)))


# ---- Visualization ----
@app.post(
    "/api/pipeline/bar-chart",
    tags=["Visualization"],
    summary="Render a bar chart",
    description="[Visualization] Render a bar chart (HTML): category frequency (no `value_column`) or category->summed value; `series_column` groups bars, `top_n` keeps the largest categories, `exclude` drops comma-separated categories. Queues a background task and returns its task_id.",
)
def bar_chart(data: BarChartRequest, user=CurrentUser):
    return _queue(user, "bar_chart", data.csv_name, data.category_column, data.value_column, data.series_column, data.title, data.output_name, data.top_n, data.exclude, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@app.post(
    "/api/pipeline/scatter-plot",
    tags=["Visualization"],
    summary="Render a scatter / bubble plot",
    description="[Visualization] Render a 2D scatter plot (HTML) from `x_column`/`y_column` or a stringified '[x, y]' `coord_column`; `color_column` tints by category, `size_column` makes a bubble chart. Queues a background task and returns its task_id.",
)
def scatter_plot(data: ScatterPlotRequest, user=CurrentUser):
    return _queue(user, "scatter_plot", data.csv_name, data.x_column, data.y_column, data.color_column, data.size_column, data.coord_column, data.title, data.output_name, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@app.post(
    "/api/pipeline/histogram",
    tags=["Visualization"],
    summary="Render a histogram of a numeric column",
    description="[Visualization] Render a histogram (HTML) of `value_column`'s distribution across `bins` buckets; `color_column` overlays series, `log_x`/`log_y` switch that axis to log scale. Queues a background task and returns its task_id.",
)
def histogram(data: HistogramRequest, user=CurrentUser):
    return _queue(user, "histogram", data.csv_name, data.value_column, data.bins, data.title, data.output_name, data.color_column, data.log_x, data.log_y, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@app.post(
    "/api/pipeline/line-chart",
    tags=["Visualization"],
    summary="Render a line chart over a sorted x-axis",
    description="[Visualization] Render a line chart (HTML) of `y_column` against a sorted `x_column` (e.g. counts per year); `color_column` draws one line per category. Queues a background task and returns its task_id.",
)
def line_chart(data: LineChartRequest, user=CurrentUser):
    return _queue(user, "line_chart", data.csv_name, data.x_column, data.y_column, data.color_column, data.title, data.output_name, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@app.post(
    "/api/pipeline/box-plot",
    tags=["Visualization"],
    summary="Render a box plot of a distribution",
    description="[Visualization] Render a box plot (HTML) of `value_column`'s distribution, optionally split by `category_column`; `exclude` drops comma-separated categories, `log_y` uses a log y-axis. Queues a background task and returns its task_id.",
)
def box_plot(data: BoxPlotRequest, user=CurrentUser):
    return _queue(user, "box_plot", data.csv_name, data.value_column, data.category_column, data.title, data.output_name, data.exclude, data.log_y, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@app.post(
    "/api/pipeline/heatmap",
    tags=["Visualization"],
    summary="Render a heatmap (density or mean)",
    description="[Visualization] Render a heatmap (HTML): (x, y) count density with no `value_column`, or the mean of `value_column` per (x, y) cell. Queues a background task and returns its task_id.",
)
def heatmap(data: HeatmapRequest, user=CurrentUser):
    return _queue(user, "heatmap", data.csv_name, data.x_column, data.y_column, data.value_column, data.title, data.output_name, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@app.post(
    "/api/pipeline/pie-chart",
    tags=["Visualization"],
    summary="Render a pie chart of category shares",
    description="[Visualization] Render a pie chart (HTML) of category proportions by row count or summed `value_column`; `top_n` keeps the largest slices, `exclude` drops comma-separated categories. Queues a background task and returns its task_id.",
)
def pie_chart(data: PieChartRequest, user=CurrentUser):
    return _queue(user, "pie_chart", data.csv_name, data.category_column, data.value_column, data.title, data.output_name, data.top_n, data.exclude, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@app.post(
    "/api/pipeline/hierarchical-dendrogram",
    tags=["Visualization"],
    summary="Render a hierarchical topic dendrogram",
    description=(
        "[Visualization] Render an HTML dendrogram of a corpus's topics: each topic is "
        "reduced to the mean of its members' `embedding_column` vectors, the centroids "
        "are joined bottom-up with Ward hierarchical clustering, and the tree shows "
        "which topics fuse into broader super-themes. Keeps the `top_n` largest topics; "
        "leaves are labelled with each topic's top keywords + size; noise (-1) is "
        "excluded. Queues a background task and returns its task_id."
    ),
)
def hierarchical_dendrogram(data: HierarchicalDendrogramRequest, user=CurrentUser):
    return _queue(user, "hierarchical_dendrogram", data.csv_name, data.topic_column, data.text_column, data.embedding_column, data.output_name, data.title, data.top_n, data.orientation, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))
