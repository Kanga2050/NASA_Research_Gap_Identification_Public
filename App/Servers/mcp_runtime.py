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
from App.Frontend.webapp.storage import user_csv_root, user_html_root

from Servers.Getter_Functions.Get_Csv_Catalog import get_csv_catalog as _get_csv_catalog
from Servers.Getter_Functions.Get_Csv_Segment import get_csv_segment as _get_csv_segment
from Servers.Getter_Functions.List_Html_Files import list_html_files as _list_html_files

mcp = FastMCP("NLP Analysis Platform")


def _get_user(api_key: str):
    resolved = resolve_api_key(api_key)
    if resolved is None:
        raise ValueError("Invalid API key")
    return resolved.user


@mcp.tool()
def get_task_status(api_key: str, task_id: str):
    user = _get_user(api_key)
    return _get_task_status(task_id, user=user)


@mcp.tool()
def get_task_history(api_key: str, limit: int = 20):
    user = _get_user(api_key)
    return _get_task_history(user=user, limit=limit)


@mcp.tool()
def get_csv_catalog(api_key: str):
    user = _get_user(api_key)
    return _get_csv_catalog(user_csv_root(user))


@mcp.tool()
def list_html_files(api_key: str):
    user = _get_user(api_key)
    return _list_html_files(user_html_root(user))


@mcp.tool()
def get_csv_segment(api_key: str, csv_name: str, start_row: int, num_rows: int, columns: str):
    user = _get_user(api_key)
    return _get_csv_segment(csv_name, start_row, num_rows, columns, user_csv_root(user))


@mcp.tool(name="embed_text")
def embed_text(api_key: str, csv_name: str, text_column: str = "abstract", embedding_column: str = "abstract_embedding", model: str = "allenai/specter2_base") -> dict:
    user = _get_user(api_key)
    return queue_user_task(user, "embed_text", csv_name, text_column, embedding_column, model, csv_root=str(user_csv_root(user)))


@mcp.tool(name="reduce_dimensionality")
def reduce_dimensionality(api_key: str, csv_name: str, output_column: str, n_components: int, embedding_column: str = "abstract_embedding") -> dict:
    user = _get_user(api_key)
    return queue_user_task(user, "reduce_dimensionality", csv_name, embedding_column, output_column, n_components, csv_root=str(user_csv_root(user)))


@mcp.tool(name="cluster")
def cluster(api_key: str, csv_name: str, coordinate_column: str = "5d", output_column: str = "topic_id", min_cluster_size: int = 32, min_samples: int = 8) -> dict:
    user = _get_user(api_key)
    return queue_user_task(user, "cluster", csv_name, coordinate_column, output_column, min_cluster_size, min_samples, csv_root=str(user_csv_root(user)))


@mcp.tool(name="distance_map")
def distance_map(api_key: str, csv_name: str, topic_column: str = "topic_id", text_column: str = "abstract", coordinate_column: str = "2d", output_name: str = "Space_Biology_Topics") -> dict:
    user = _get_user(api_key)
    return queue_user_task(user, "distance_map", csv_name, topic_column, text_column, coordinate_column, output_name, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@mcp.tool(name="keyword_score")
def keyword_score(api_key: str, csv_name: str, query: str, text_column: str = "abstract", new_column_name: str = "kw") -> dict:
    user = _get_user(api_key)
    return queue_user_task(user, "keyword_score", csv_name, query, text_column, new_column_name, csv_root=str(user_csv_root(user)))


@mcp.tool(name="semantic_score")
def semantic_score(api_key: str, csv_name: str, query: str, embedding_column: str = "abstract_embedding", new_column_name: str = "sem") -> dict:
    user = _get_user(api_key)
    return queue_user_task(user, "semantic_score", csv_name, query, embedding_column, new_column_name, csv_root=str(user_csv_root(user)))


@mcp.tool(name="hybrid_score")
def hybrid_score(api_key: str, csv_name: str, keyword_col: str = "kw", semantic_col: str = "sem", new_column_name: str = "hybrid") -> dict:
    user = _get_user(api_key)
    return queue_user_task(user, "hybrid_score", csv_name, keyword_col, semantic_col, new_column_name, csv_root=str(user_csv_root(user)))


@mcp.tool(name="numerical_filter")
def numerical_filter(api_key: str, source_csv: str, output_csv: str = "Filtered_Output", target_score_column: str = "hybrid", threshold: float = 0.70) -> dict:
    user = _get_user(api_key)
    return queue_user_task(user, "numerical_filter", source_csv, output_csv, target_score_column, threshold, csv_root=str(user_csv_root(user)))


@mcp.tool(name="openalex_scraper")
def openalex_scraper(api_key: str, topic: str, csv_name: str = "scraped", limit: int = 10000) -> dict:
    user = _get_user(api_key)
    return queue_user_task(user, "openalex_scraper", topic, csv_name, limit, csv_root=str(user_csv_root(user)))


# ---- Distillation ----
@mcp.tool(name="categorical_filter")
def categorical_filter(api_key: str, source_csv: str, output_csv: str, target_column: str, expected_value: str) -> dict:
    """Extract rows whose target_column exactly equals expected_value into a new CSV (e.g. isolate topic_id 1)."""
    user = _get_user(api_key)
    return queue_user_task(user, "categorical_filter", source_csv, output_csv, target_column, expected_value, csv_root=str(user_csv_root(user)))


@mcp.tool(name="combine_csvs")
def combine_csvs(api_key: str, source_csvs: str, output_csv: str = "Combined_Corpus", source_column: str = "source") -> dict:
    """Stack several CSVs (comma-separated names in source_csvs) into one, tagging each row's origin in source_column."""
    user = _get_user(api_key)
    return queue_user_task(user, "combine_csvs", source_csvs, output_csv, source_column, csv_root=str(user_csv_root(user)))


@mcp.tool(name="aggregate_dictionary")
def aggregate_dictionary(api_key: str, source_csv: str, output_csv: str, dict_column: str = "word_freq") -> dict:
    """Sum the per-row {key: number} dictionaries in dict_column across all rows into a new [key, sum] CSV."""
    user = _get_user(api_key)
    return queue_user_task(user, "aggregate_dictionary", source_csv, output_csv, dict_column, csv_root=str(user_csv_root(user)))


@mcp.tool(name="group_aggregate")
def group_aggregate(api_key: str, source_csv: str, output_csv: str, group_column: str, value_column: str = "", agg: str = "count", exclude: str = "") -> dict:
    """Group rows by group_column and aggregate (count/mean/sum/min/max) into a summary CSV; exclude drops comma-separated group values (e.g. "-1" noise)."""
    user = _get_user(api_key)
    return queue_user_task(user, "group_aggregate", source_csv, output_csv, group_column, value_column, agg, exclude, csv_root=str(user_csv_root(user)))


@mcp.tool(name="top_n_by_column")
def top_n_by_column(api_key: str, source_csv: str, output_csv: str, sort_column: str, n: int = 100, ascending: bool = False) -> dict:
    """Sort by sort_column and keep the top n rows into a new CSV (threshold-free top-N)."""
    user = _get_user(api_key)
    return queue_user_task(user, "top_n_by_column", source_csv, output_csv, sort_column, n, ascending, csv_root=str(user_csv_root(user)))


@mcp.tool(name="deduplicate")
def deduplicate(api_key: str, source_csv: str, output_csv: str, subset_column: str) -> dict:
    """Drop rows that repeat a value in subset_column (keeping the first) into a new CSV."""
    user = _get_user(api_key)
    return queue_user_task(user, "deduplicate", source_csv, output_csv, subset_column, csv_root=str(user_csv_root(user)))


@mcp.tool(name="select_columns")
def select_columns(api_key: str, source_csv: str, output_csv: str, columns: str, drop: bool = False) -> dict:
    """Write a new CSV keeping only the comma-separated columns (or dropping them when drop=True)."""
    user = _get_user(api_key)
    return queue_user_task(user, "select_columns", source_csv, output_csv, columns, drop, csv_root=str(user_csv_root(user)))


@mcp.tool(name="cross_tab")
def cross_tab(api_key: str, source_csv: str, output_csv: str, row_column: str, column_column: str) -> dict:
    """Build a count matrix of row_column against column_column into a new CSV (feeds a heatmap)."""
    user = _get_user(api_key)
    return queue_user_task(user, "cross_tab", source_csv, output_csv, row_column, column_column, csv_root=str(user_csv_root(user)))


@mcp.tool(name="arithmetic")
def arithmetic(api_key: str, source_csv: str, output_csv: str, column_a: str, operation: str, operand: str, new_column: str = "result", group_by: str = "") -> dict:
    """Basic column arithmetic (add/subtract/multiply/divide): new_column = column_a <operation> operand, where operand is another column or a number. With group_by, a column operand is replaced by its per-group sum, so count/count grouped by a category gives each row's share of its group (x100 = percent)."""
    user = _get_user(api_key)
    return queue_user_task(user, "arithmetic", source_csv, output_csv, column_a, operation, operand, new_column, group_by, csv_root=str(user_csv_root(user)))


# ---- Annotation ----
@mcp.tool(name="word_frequency")
def word_frequency(api_key: str, csv_name: str, text_column: str = "abstract", new_column_name: str = "word_freq", ngram: int = 1) -> dict:
    """Annotate each row with its own {word: count} dictionary from text_column (ngram=2/3 for phrases)."""
    user = _get_user(api_key)
    return queue_user_task(user, "word_frequency", csv_name, text_column, new_column_name, ngram, csv_root=str(user_csv_root(user)))


@mcp.tool(name="label_topics")
def label_topics(api_key: str, csv_name: str, topic_column: str = "topic_id", text_column: str = "abstract", new_column_name: str = "Topic_Label", top_n: int = 3) -> dict:
    """Add a Topic_Label column mapping each topic to its top_n keywords (the labels the Distance Map shows), so charts can group by readable labels instead of raw topic numbers."""
    user = _get_user(api_key)
    return queue_user_task(user, "label_topics", csv_name, topic_column, text_column, new_column_name, top_n, csv_root=str(user_csv_root(user)))


@mcp.tool(name="text_length")
def text_length(api_key: str, csv_name: str, text_column: str = "abstract", new_column_name: str = "length", unit: str = "words") -> dict:
    """Add a column with the length of text_column, measured in words or chars."""
    user = _get_user(api_key)
    return queue_user_task(user, "text_length", csv_name, text_column, new_column_name, unit, csv_root=str(user_csv_root(user)))


@mcp.tool(name="extract_year")
def extract_year(api_key: str, csv_name: str, date_column: str = "publish_time", new_column_name: str = "year") -> dict:
    """Parse a four-digit year out of date_column into a new numeric column."""
    user = _get_user(api_key)
    return queue_user_task(user, "extract_year", csv_name, date_column, new_column_name, csv_root=str(user_csv_root(user)))


@mcp.tool(name="to_date")
def to_date(api_key: str, csv_name: str, date_column: str = "publish_time", new_column_name: str = "date") -> dict:
    """Normalize date_column into a canonical ISO-8601 (YYYY-MM-DD) date column that sorts chronologically and supports date range/threshold filtering and time-axis charts."""
    user = _get_user(api_key)
    return queue_user_task(user, "to_date", csv_name, date_column, new_column_name, csv_root=str(user_csv_root(user)))


@mcp.tool(name="normalize_column")
def normalize_column(api_key: str, csv_name: str, value_column: str, new_column_name: str = "") -> dict:
    """Min-max scale value_column to 0-1; a blank/equal new_column_name overwrites value_column in place."""
    user = _get_user(api_key)
    return queue_user_task(user, "normalize_column", csv_name, value_column, new_column_name, csv_root=str(user_csv_root(user)))


# ---- Visualization ----
@mcp.tool(name="bar_chart")
def bar_chart(api_key: str, csv_name: str, category_column: str, value_column: str = "", series_column: str = "", title: str = "", output_name: str = "bar_chart", top_n: int = 25, exclude: str = "") -> dict:
    """Render a bar chart HTML: category frequency (no value_column) or category->summed value; series_column groups bars; exclude drops comma-separated categories (e.g. "-1")."""
    user = _get_user(api_key)
    return queue_user_task(user, "bar_chart", csv_name, category_column, value_column, series_column, title, output_name, top_n, exclude, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@mcp.tool(name="scatter_plot")
def scatter_plot(api_key: str, csv_name: str, x_column: str = "", y_column: str = "", color_column: str = "", size_column: str = "", coord_column: str = "", title: str = "", output_name: str = "scatter_plot") -> dict:
    """Render a scatter plot HTML from x/y columns or a stringified [x,y] coord_column; color_column and size_column optional."""
    user = _get_user(api_key)
    return queue_user_task(user, "scatter_plot", csv_name, x_column, y_column, color_column, size_column, coord_column, title, output_name, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@mcp.tool(name="histogram")
def histogram(api_key: str, csv_name: str, value_column: str, bins: int = 30, title: str = "", output_name: str = "histogram", color_column: str = "", log_x: bool = False, log_y: bool = False) -> dict:
    """Render a histogram HTML of a numeric column's distribution; color_column overlays series, log_x/log_y switch that axis to a logarithmic scale."""
    user = _get_user(api_key)
    return queue_user_task(user, "histogram", csv_name, value_column, bins, title, output_name, color_column, log_x, log_y, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@mcp.tool(name="line_chart")
def line_chart(api_key: str, csv_name: str, x_column: str, y_column: str, color_column: str = "", title: str = "", output_name: str = "line_chart") -> dict:
    """Render a line chart HTML of y_column against a sorted x_column (e.g. counts per year)."""
    user = _get_user(api_key)
    return queue_user_task(user, "line_chart", csv_name, x_column, y_column, color_column, title, output_name, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@mcp.tool(name="box_plot")
def box_plot(api_key: str, csv_name: str, value_column: str, category_column: str = "", title: str = "", output_name: str = "box_plot", exclude: str = "", log_y: bool = False) -> dict:
    """Render a box plot HTML of value_column's distribution, optionally split by category_column; exclude drops comma-separated categories, log_y uses a log y-axis."""
    user = _get_user(api_key)
    return queue_user_task(user, "box_plot", csv_name, value_column, category_column, title, output_name, exclude, log_y, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@mcp.tool(name="heatmap")
def heatmap(api_key: str, csv_name: str, x_column: str, y_column: str, value_column: str = "", title: str = "", output_name: str = "heatmap") -> dict:
    """Render a heatmap HTML: (x,y) count density, or mean of value_column per (x,y) cell."""
    user = _get_user(api_key)
    return queue_user_task(user, "heatmap", csv_name, x_column, y_column, value_column, title, output_name, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


@mcp.tool(name="pie_chart")
def pie_chart(api_key: str, csv_name: str, category_column: str, value_column: str = "", title: str = "", output_name: str = "pie_chart", top_n: int = 10, exclude: str = "") -> dict:
    """Render a pie chart HTML of category proportions by row count or summed value_column; exclude drops comma-separated categories (e.g. "-1")."""
    user = _get_user(api_key)
    return queue_user_task(user, "pie_chart", csv_name, category_column, value_column, title, output_name, top_n, exclude, csv_root=str(user_csv_root(user)), html_root=str(user_html_root(user)))


FOLDER = "App/Backend/Visualizations"


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
    user = _get_user(api_key)
    html_root = str(user_html_root(user))
    filepath = os.path.join(html_root, filename)
    if not os.path.abspath(filepath).startswith(os.path.abspath(html_root)):
        return "<h1>Error: Invalid file path</h1>"
    if not os.path.isfile(filepath):
        return f"<h1>Error: {filename} not found</h1>"
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()
