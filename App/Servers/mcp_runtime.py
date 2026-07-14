import os
import sys

from fastmcp import FastMCP
from fastmcp.apps import AppConfig

current_dir = os.path.dirname(os.path.abspath(__file__))
target_path = os.path.abspath(os.path.join(current_dir, ".."))
if target_path not in sys.path:
    sys.path.append(target_path)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "App.Frontend.webapp.settings")

import django

django.setup()

from App.Frontend.portal.services import resolve_api_key
from App.Frontend.portal.task_engine import get_task_history as _get_task_history, get_task_status as _get_task_status, queue_user_task
from App.Frontend.webapp.storage import user_csv_root, user_html_root, user_pdf_root

from Servers.Getter_Functions.Get_Csv_Catalog import get_csv_catalog as _get_csv_catalog
from Servers.Getter_Functions.Get_Csv_Segment import get_csv_segment as _get_csv_segment
from Servers.Getter_Functions.List_Html_Files import list_html_files as _list_html_files
from Servers.Getter_Functions.List_Pdf_Folders import list_pdf_folders as _list_pdf_folders

mcp = FastMCP("NLP Analysis Platform")


def _get_user(api_key: str):
    resolved = resolve_api_key(api_key)
    if resolved is None:
        raise ValueError("Invalid API key")
    return resolved.user


@mcp.tool()
def get_task_status(api_key: str, task_id: str):
    """Look up one queued/running/finished task by its `task_id`. Returns its status
    (queued/working/completed/failed/cancelled), the function that ran, timestamps,
    any error, and `latest_print` -- the most recent progress line the task emitted.
    Poll this after queuing a pipeline task to watch it progress to completion."""
    user = _get_user(api_key)
    return _get_task_status(task_id, user=user)


@mcp.tool()
def get_task_history(api_key: str, limit: int = 20):
    """List this user's most recent tasks (newest first, up to `limit`), each with
    its status, function name, timestamps and latest progress line. Use it to review
    what has run or to find the task_id of a job you queued earlier."""
    user = _get_user(api_key)
    return _get_task_history(user=user, limit=limit)


@mcp.tool()
def get_csv_catalog(api_key: str):
    """List every CSV dataset in this user's workspace along with its columns and row
    count. Call this first to discover what data exists and which column names to
    pass to the pipeline tools."""
    user = _get_user(api_key)
    return _get_csv_catalog(user_csv_root(user))


@mcp.tool()
def list_html_files(api_key: str):
    """List the rendered visualization HTML files (charts, maps) in this user's
    workspace. Pass one of these names to `display_html_file` to view it."""
    user = _get_user(api_key)
    return _list_html_files(user_html_root(user))


@mcp.tool()
def get_csv_segment(api_key: str, csv_name: str, start_row: int, num_rows: int, columns: str):
    """Read a slice of a CSV: `num_rows` rows starting at `start_row` (0-based),
    limited to the comma-separated `columns`. Use it to preview or page through a
    dataset without loading the whole (potentially huge) file."""
    user = _get_user(api_key)
    return _get_csv_segment(csv_name, start_row, num_rows, columns, user_csv_root(user))


@mcp.tool(name="embed_text")
def embed_text(api_key: str, csv_name: str, text_column: str = "text", embedding_column: str = "text_embedding", model: str = "allenai/specter2_base") -> dict:
    """[Annotation] Compute a semantic embedding vector for each row's `text_column`
    and store it (stringified) in `embedding_column`, editing the CSV in place. This
    is the foundation for semantic search, dimensionality reduction and clustering.
    Slow on large datasets. Queues a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "embed_text", csv_name, text_column, embedding_column, model, csv_root=str(user_csv_root(user)))


@mcp.tool(name="reduce_dimensionality")
def reduce_dimensionality(api_key: str, csv_name: str, output_column: str, n_components: int, embedding_column: str = "text_embedding") -> dict:
    """[Annotation] Run UMAP to compress high-dimensional embeddings in
    `embedding_column` down to `n_components` dimensions, written to `output_column`
    (stringified coordinates). Use n=2 for a plottable "2d" map, or n=5 as the "5d"
    input to clustering. Queues a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "reduce_dimensionality", csv_name, embedding_column, output_column, n_components, csv_root=str(user_csv_root(user)))


@mcp.tool(name="cluster")
def cluster(api_key: str, csv_name: str, coordinate_column: str = "5d", output_column: str = "topic_id", min_cluster_size: int = 32, min_samples: int = 8) -> dict:
    """[Annotation] Group rows into topics with HDBSCAN over the coordinates in
    `coordinate_column` (e.g. the "5d" UMAP column), writing a topic id per row into
    `output_column`. Larger `min_cluster_size`/`min_samples` yield fewer, tighter
    topics; id -1 is noise (not a topic). Queues a background task; returns task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "cluster", csv_name, coordinate_column, output_column, min_cluster_size, min_samples, csv_root=str(user_csv_root(user)))


@mcp.tool(name="distance_map")
def distance_map(api_key: str, csv_name: str, topic_column: str = "topic_id", text_column: str = "text", coordinate_column: str = "2d", output_name: str = "Space_Biology_Topics") -> dict:
    """[Visualization] Render an intertopic distance map (HTML): one bubble per topic
    positioned at its mean 2D coordinate, sized by document count and labelled with
    its top keywords. Needs a `coordinate_column` of "[x, y]" pairs and a
    `topic_column`. Queues a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "distance_map", csv_name, topic_column, text_column, coordinate_column, output_name, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@mcp.tool(name="keyword_score")
def keyword_score(api_key: str, csv_name: str, query: str, text_column: str = "text", new_column_name: str = "kw") -> dict:
    """[Annotation] Score every row for lexical (keyword) relevance to `query` using
    TF-IDF cosine similarity over `text_column`, writing a 0-1 score into
    `new_column_name`. Rewards exact word overlap. Pair with `semantic_score` +
    `hybrid_score` for best retrieval. Queues a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "keyword_score", csv_name, query, text_column, new_column_name, csv_root=str(user_csv_root(user)))


@mcp.tool(name="semantic_score")
def semantic_score(api_key: str, csv_name: str, query: str, embedding_column: str = "text_embedding", new_column_name: str = "sem") -> dict:
    """[Annotation] Score every row for meaning-based (semantic) relevance to `query`
    by cosine similarity between the query's embedding and each row's stored
    `embedding_column`, writing a score into `new_column_name`. Catches paraphrases
    keyword search misses (requires `embed_text` first). Queues a task; returns task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "semantic_score", csv_name, query, embedding_column, new_column_name, csv_root=str(user_csv_root(user)))


@mcp.tool(name="hybrid_score")
def hybrid_score(api_key: str, csv_name: str, keyword_col: str = "kw", semantic_col: str = "sem", new_column_name: str = "hybrid") -> dict:
    """[Annotation] Fuse a keyword score column and a semantic score column into one
    combined 0-1 relevance score (Reciprocal Rank Fusion) in `new_column_name`,
    balancing exact-match and meaning-based retrieval. Run after `keyword_score` and
    `semantic_score`. Queues a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "hybrid_score", csv_name, keyword_col, semantic_col, new_column_name, csv_root=str(user_csv_root(user)))


@mcp.tool(name="numerical_filter")
def numerical_filter(api_key: str, source_csv: str, output_csv: str = "Filtered_Output", target_score_column: str = "hybrid", threshold: float = 0.70) -> dict:
    """[Distillation] Keep only rows whose `target_score_column` is >= `threshold`,
    writing them (sorted best-first) to a new `output_csv`. Works on numeric columns
    or ISO-8601 date columns (a date threshold filters chronologically). Great for
    isolating the most relevant papers. Queues a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "numerical_filter", source_csv, output_csv, target_score_column, threshold, csv_root=str(user_csv_root(user)))


@mcp.tool(name="openalex_scraper")
def openalex_scraper(api_key: str, topic: str, csv_name: str = "scraped", limit: int = 10000) -> dict:
    """[Import] Download up to `limit` scholarly works matching `topic` (that have an
    abstract) from the OpenAlex API into a brand-new `csv_name` CSV, with title,
    abstract, authors, journal, DOI and publish date. This is the usual starting
    point of a pipeline. Queues a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "openalex_scraper", topic, csv_name, limit, csv_root=str(user_csv_root(user)))


@mcp.tool(name="list_pdf_folders")
def list_pdf_folders(api_key: str) -> str:
    """[Catalog] List the PDF collection folders you can chunk -- your own uploaded
    folders first, then the shared public library -- with each one's PDF count. Pass
    one or more of these names (comma-separated) to `chunk_pdfs`."""
    user = _get_user(api_key)
    return _list_pdf_folders(user_pdf_root(user))


@mcp.tool(name="chunk_pdfs")
def chunk_pdfs(api_key: str, folders: str, csv_name: str = "pdf_chunks", source_label: str = "",
               chunk_words: int = 250, overlap_words: int = 40, enrich: bool = True) -> dict:
    """[Import] Turn one or more PDF collections into a brand-new `csv_name` CSV, one row
    per sentence-aware chunk (~`chunk_words` words with ~`overlap_words` overlap, never
    cutting a sentence). `folders` is a comma-separated list of collection names from
    your PDF area or the public library (call `list_pdf_folders` to see them). Each row
    has the chunk in a `text` column plus provenance (source_file, source, doi, title,
    authors, journal, publish_time); `source_label` tags the origin (defaults to the
    collection name). With `enrich`, DOI-named PDFs (e.g. OSDR) are looked up on Crossref
    for clean authors/journal/title. Feed `text` through embed_text ->
    reduce_dimensionality -> cluster -> label_topics to match Space_Biology's columns.
    Queues a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "chunk_pdfs", folders, csv_name, source_label,
                           chunk_words, overlap_words, enrich,
                           csv_root=str(user_csv_root(user)), pdf_root=str(user_pdf_root(user)))


# ---- Distillation ----
@mcp.tool(name="categorical_filter")
def categorical_filter(api_key: str, source_csv: str, output_csv: str, target_column: str, expected_value: str) -> dict:
    """[Distillation] Keep only rows whose `target_column` exactly equals
    `expected_value` (compared as text), writing them to a new `output_csv` -- e.g.
    isolate a single topic with target_column="topic_id", expected_value="1". Queues
    a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "categorical_filter", source_csv, output_csv, target_column, expected_value, csv_root=str(user_csv_root(user)))


@mcp.tool(name="combine_csvs")
def combine_csvs(api_key: str, source_csvs: str, output_csv: str = "Combined_Corpus", source_column: str = "source") -> dict:
    """[Distillation] Stack several CSVs (comma-separated names in `source_csvs`, e.g.
    "Microgravity,Space_Crops") into one, adding `source_column` that tags each row
    with the file it came from. Queues a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "combine_csvs", source_csvs, output_csv, source_column, csv_root=str(user_csv_root(user)))


@mcp.tool(name="aggregate_dictionary")
def aggregate_dictionary(api_key: str, source_csv: str, output_csv: str, dict_column: str = "word_freq") -> dict:
    """[Distillation] Sum the per-row {key: number} dictionaries stored in
    `dict_column` across every row into a new two-column [key, sum] CSV, sorted by
    total. Pairs with `word_frequency` to build a corpus-wide word-count table for a
    bar chart. Queues a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "aggregate_dictionary", source_csv, output_csv, dict_column, csv_root=str(user_csv_root(user)))


@mcp.tool(name="group_aggregate")
def group_aggregate(api_key: str, source_csv: str, output_csv: str, group_column: str, value_column: str = "", agg: str = "count", exclude: str = "") -> dict:
    """[Distillation] Group rows by `group_column` and aggregate them into a summary
    CSV: with agg="count" (or no `value_column`) it counts rows per group, otherwise
    it applies mean/sum/min/max to `value_column`. Pass a comma-separated
    `group_column` ("Topic_Label,year") for multi-dimensional counts; `exclude` drops
    comma-separated group values (e.g. "-1" noise). Queues a task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "group_aggregate", source_csv, output_csv, group_column, value_column, agg, exclude, csv_root=str(user_csv_root(user)))


@mcp.tool(name="top_n_by_column")
def top_n_by_column(api_key: str, source_csv: str, output_csv: str, sort_column: str, n: int = 100, ascending: bool = False) -> dict:
    """[Distillation] Sort by `sort_column` and keep the top `n` rows into a new CSV
    (`ascending=True` keeps the smallest). Unlike `numerical_filter` this is
    threshold-free -- e.g. "top 100 papers by favorability". Queues a background task;
    returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "top_n_by_column", source_csv, output_csv, sort_column, n, ascending, csv_root=str(user_csv_root(user)))


@mcp.tool(name="deduplicate")
def deduplicate(api_key: str, source_csv: str, output_csv: str, subset_column: str) -> dict:
    """[Distillation] Drop rows that repeat a value in `subset_column` (keeping the
    first occurrence) and write the de-duplicated rows to a new CSV -- e.g. dedupe
    papers by title or doi. Queues a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "deduplicate", source_csv, output_csv, subset_column, csv_root=str(user_csv_root(user)))


@mcp.tool(name="select_columns")
def select_columns(api_key: str, source_csv: str, output_csv: str, columns: str, drop: bool = False) -> dict:
    """[Distillation] Write a new CSV keeping only the comma-separated `columns` (or,
    with `drop=True`, keeping everything EXCEPT them). Handy for stripping a heavy
    embedding column before export. Queues a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "select_columns", source_csv, output_csv, columns, drop, csv_root=str(user_csv_root(user)))


@mcp.tool(name="cross_tab")
def cross_tab(api_key: str, source_csv: str, output_csv: str, row_column: str, column_column: str) -> dict:
    """[Distillation] Build a contingency table counting how many rows fall into each
    (`row_column`, `column_column`) pairing, as a matrix CSV (one column per distinct
    column_column value) -- the shape a `heatmap` expects. Queues a task; returns task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "cross_tab", source_csv, output_csv, row_column, column_column, csv_root=str(user_csv_root(user)))


@mcp.tool(name="arithmetic")
def arithmetic(api_key: str, source_csv: str, output_csv: str, column_a: str, operation: str, operand: str, new_column: str = "result", group_by: str = "") -> dict:
    """[Distillation] Column arithmetic: write `new_column = column_a <operation>
    operand` (add/subtract/multiply/divide) to a new CSV, where `operand` is another
    column or a numeric constant. With `group_by`, a column operand is replaced by its
    per-group SUM, so count/count grouped by a category gives each row's share of its
    group (x100 = percent). Queues a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "arithmetic", source_csv, output_csv, column_a, operation, operand, new_column, group_by, csv_root=str(user_csv_root(user)))


# ---- Annotation ----
@mcp.tool(name="word_frequency")
def word_frequency(api_key: str, csv_name: str, text_column: str = "text", new_column_name: str = "word_freq", ngram: int = 1) -> dict:
    """[Annotation] Annotate each row with its own {word: count} dictionary from
    `text_column` (lemmatized, stop-word filtered), stored in `new_column_name`. Set
    `ngram`=2 or 3 to count phrases. Feed the result to `aggregate_dictionary` for a
    corpus-wide word table. Queues a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "word_frequency", csv_name, text_column, new_column_name, ngram, csv_root=str(user_csv_root(user)))


@mcp.tool(name="label_topics")
def label_topics(api_key: str, csv_name: str, topic_column: str = "topic_id", text_column: str = "text", new_column_name: str = "Topic_Label", top_n: int = 3) -> dict:
    """[Annotation] Add a `new_column_name` (default Topic_Label) mapping each row's
    topic to that topic's top `top_n` keywords, so charts can group by readable labels
    instead of raw topic numbers. Run after `cluster`. Queues a task; returns task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "label_topics", csv_name, topic_column, text_column, new_column_name, top_n, csv_root=str(user_csv_root(user)))


@mcp.tool(name="text_length")
def text_length(api_key: str, csv_name: str, text_column: str = "text", new_column_name: str = "length", unit: str = "words") -> dict:
    """[Annotation] Add a numeric column with the length of `text_column`, measured in
    `unit`="words" or "chars" -- e.g. a scatter-plot axis of abstract length vs.
    favorability. Queues a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "text_length", csv_name, text_column, new_column_name, unit, csv_root=str(user_csv_root(user)))


@mcp.tool(name="extract_year")
def extract_year(api_key: str, csv_name: str, date_column: str = "publish_time", new_column_name: str = "year") -> dict:
    """[Annotation] Parse a four-digit year out of `date_column` into a new numeric
    column, unlocking temporal charts (e.g. publications per year). Queues a background
    task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "extract_year", csv_name, date_column, new_column_name, csv_root=str(user_csv_root(user)))


@mcp.tool(name="to_date")
def to_date(api_key: str, csv_name: str, date_column: str = "publish_time", new_column_name: str = "date") -> dict:
    """[Annotation] Normalize `date_column` into a canonical ISO-8601 (YYYY-MM-DD)
    date column that sorts chronologically and supports date range/threshold filtering
    (via `numerical_filter`) and time-axis charts. Queues a task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "to_date", csv_name, date_column, new_column_name, csv_root=str(user_csv_root(user)))


@mcp.tool(name="normalize_column")
def normalize_column(api_key: str, csv_name: str, value_column: str, new_column_name: str = "") -> dict:
    """[Annotation] Min-max scale `value_column` into the 0-1 range. A blank (or equal)
    `new_column_name` overwrites `value_column` in place; otherwise the scaled values
    land in a new column. Queues a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "normalize_column", csv_name, value_column, new_column_name, csv_root=str(user_csv_root(user)))


@mcp.tool(name="hierarchical_cluster")
def hierarchical_cluster(api_key: str, csv_name: str, topic_column: str = "topic_id", embedding_column: str = "5d", output_column: str = "hcluster", n_clusters: int = 10) -> dict:
    """[Annotation] Agglomerate an existing `topic_column` into `n_clusters` broader
    hierarchical "super-clusters", writing each row's super-cluster id into
    `output_column`. Each topic is reduced to the centroid of its members'
    `embedding_column` vectors, the centroids are Ward-linked, and the tree is cut into
    `n_clusters` groups -- a coarser, top-down complement to HDBSCAN's flat `cluster`
    where every topic lands in a theme (only noise stays -1). Queues a task; returns task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "hierarchical_cluster", csv_name, topic_column, embedding_column, output_column, n_clusters, csv_root=str(user_csv_root(user)))


# ---- Visualization ----
@mcp.tool(name="bar_chart")
def bar_chart(api_key: str, csv_name: str, category_column: str, value_column: str = "", series_column: str = "", title: str = "", output_name: str = "bar_chart", top_n: int = 25, exclude: str = "") -> dict:
    """[Visualization] Render a bar chart (HTML): with no `value_column` it counts the
    frequency of each `category_column` value, with one it sums that value per
    category. `series_column` splits bars into grouped sub-bars; `top_n` keeps the
    largest categories; `exclude` drops comma-separated categories (e.g. "-1"). Queues
    a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "bar_chart", csv_name, category_column, value_column, series_column, title, output_name, top_n, exclude, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@mcp.tool(name="scatter_plot")
def scatter_plot(api_key: str, csv_name: str, x_column: str = "", y_column: str = "", color_column: str = "", size_column: str = "", coord_column: str = "", title: str = "", output_name: str = "scatter_plot") -> dict:
    """[Visualization] Render a 2D scatter plot (HTML) from two numeric columns
    (`x_column`, `y_column`) or a single `coord_column` of stringified "[x, y]" pairs
    (like the "2d" UMAP column). `color_column` tints points by category; `size_column`
    scales them into a bubble chart. Queues a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "scatter_plot", csv_name, x_column, y_column, color_column, size_column, coord_column, title, output_name, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@mcp.tool(name="histogram")
def histogram(api_key: str, csv_name: str, value_column: str, bins: int = 30, title: str = "", output_name: str = "histogram", color_column: str = "", log_x: bool = False, log_y: bool = False) -> dict:
    """[Visualization] Render a histogram (HTML) of a numeric `value_column`'s
    distribution across `bins` buckets. `color_column` overlays one series per
    category; `log_x`/`log_y` switch that axis to a logarithmic scale (useful when
    counts span orders of magnitude). Queues a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "histogram", csv_name, value_column, bins, title, output_name, color_column, log_x, log_y, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@mcp.tool(name="line_chart")
def line_chart(api_key: str, csv_name: str, x_column: str, y_column: str, color_column: str = "", title: str = "", output_name: str = "line_chart") -> dict:
    """[Visualization] Render a line chart (HTML) of `y_column` against a sorted
    `x_column` (e.g. paper counts per year). `color_column` draws one line per
    category. Pre-aggregate with `group_aggregate` for one point per x value. Queues a
    background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "line_chart", csv_name, x_column, y_column, color_column, title, output_name, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@mcp.tool(name="box_plot")
def box_plot(api_key: str, csv_name: str, value_column: str, category_column: str = "", title: str = "", output_name: str = "box_plot", exclude: str = "", log_y: bool = False) -> dict:
    """[Visualization] Render a box plot (HTML) of `value_column`'s distribution
    (median, quartiles, outliers). Pass `category_column` to draw one box per category
    (e.g. favorability spread per topic); `exclude` drops comma-separated categories;
    `log_y` uses a log y-axis. Queues a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "box_plot", csv_name, value_column, category_column, title, output_name, exclude, log_y, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@mcp.tool(name="heatmap")
def heatmap(api_key: str, csv_name: str, x_column: str, y_column: str, value_column: str = "", title: str = "", output_name: str = "heatmap") -> dict:
    """[Visualization] Render a heatmap (HTML): with no `value_column` it shows the
    count density of (x, y) pairs; with one, it shows the mean of `value_column` for
    each (x, y) cell. Queues a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "heatmap", csv_name, x_column, y_column, value_column, title, output_name, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@mcp.tool(name="pie_chart")
def pie_chart(api_key: str, csv_name: str, category_column: str, value_column: str = "", title: str = "", output_name: str = "pie_chart", top_n: int = 10, exclude: str = "") -> dict:
    """[Visualization] Render a pie chart (HTML) of category proportions: by row count
    (no `value_column`) or by summed `value_column` per category. `top_n` keeps the
    largest slices; `exclude` drops comma-separated categories (e.g. "-1"). Queues a
    background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "pie_chart", csv_name, category_column, value_column, title, output_name, top_n, exclude, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@mcp.tool(name="hierarchical_dendrogram")
def hierarchical_dendrogram(api_key: str, csv_name: str, topic_column: str = "topic_id", text_column: str = "text", embedding_column: str = "5d", output_name: str = "Topic_Dendrogram", title: str = "", top_n: int = 30, orientation: str = "left") -> dict:
    """[Visualization] Render an HTML dendrogram of a corpus's topics. Each topic is
    reduced to the mean of its members' `embedding_column` vectors, the centroids are
    joined bottom-up with Ward hierarchical clustering, and the tree shows which topics
    fuse into broader super-themes and how far apart branches sit. Keeps the `top_n`
    largest topics so the tree stays legible; leaves are labelled with each topic's top
    keywords + size; noise (-1) is excluded. Queues a background task; returns its task_id."""
    user = _get_user(api_key)
    return queue_user_task(user, "hierarchical_dendrogram", csv_name, topic_column, text_column, embedding_column, output_name, title, top_n, orientation, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@mcp.resource("ui://viewer/app.html")
def viewer_app() -> str:
    return """<!DOCTYPE html>
<html>
<head>
    <meta charset=\"utf-8\">
    <script type=\"module\">
        import { App } from \"https://unpkg.com/@modelcontextprotocol/ext-apps@0.4.0/app-with-deps\";
        const app = new App({ name: \"HTML Viewer\", version: \"1.0.0\" });
        app.ontoolresult = ({ content }) => {
            const text = content?.find(c => c.type === 'text');
            if (text) document.getElementById('container').innerHTML = text.text;
        };
        await app.connect();
    </script>
</head>
<body>
    <div id=\"container\">Loading requested file...</div>
</body>
</html>"""


@mcp.tool(app=AppConfig(resource_uri="ui://viewer/app.html"))
def display_html_file(api_key: str, filename: str) -> str:
    """Load and display one of this user's rendered visualization HTML files (as
    listed by `list_html_files`) inside the interactive viewer. Pass the file name
    including its .html extension, e.g. "Topic_Share_Pie.html"."""
    user = _get_user(api_key)
    html_root = str(user_html_root(user))
    filepath = os.path.join(html_root, filename)
    if not os.path.abspath(filepath).startswith(os.path.abspath(html_root)):
        return "<h1>Error: Invalid file path</h1>"
    if not os.path.isfile(filepath):
        return f"<h1>Error: {filename} not found</h1>"
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()
