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
