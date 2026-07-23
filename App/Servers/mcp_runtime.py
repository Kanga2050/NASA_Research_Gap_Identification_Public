import json
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

from App.Frontend.portal import paper_ops, studio_ops
from App.Frontend.portal.services import resolve_api_key
from App.Frontend.portal.task_engine import get_task_history as _get_task_history, get_task_status as _get_task_status, queue_user_task
from App.Frontend.webapp.storage import user_csv_root, user_html_root, user_pdf_root
from App.Servers.pipeline_tools import queue_from_api, register_mcp_tools

from Servers.Getter_Functions.Get_Csv_Catalog import get_csv_catalog as _get_csv_catalog
from Servers.Getter_Functions.Get_Csv_Segment import get_csv_segment as _get_csv_segment
from Servers.Getter_Functions.List_Html_Files import list_html_files as _list_html_files
from Servers.Getter_Functions.List_Pdf_Folders import list_pdf_folders as _list_pdf_folders

mcp = FastMCP("NLP Analysis Platform")

ROOT_BUILDERS = {"csv": user_csv_root, "html": user_html_root, "pdf": user_pdf_root}


def _get_user(api_key: str):
    resolved = resolve_api_key(api_key)
    if resolved is None:
        raise ValueError("Invalid API key")
    return resolved.user


# --------------------------------------------------------------------------- #
# The pipeline tools (Import / Annotation / Distillation / Visualization).
#
# One tool per function in App.Backend.registry, generated from that registry -- which
# already holds every function's arguments, defaults, storage roots and documentation.
# Hand-writing them here meant maintaining a second copy of all of it (and a second,
# subtly different wording of every docstring) that nothing kept honest.
# --------------------------------------------------------------------------- #
register_mcp_tools(mcp, queue_from_api(queue_user_task, ROOT_BUILDERS), _get_user)


# --------------------------------------------------------------------------- #
# Tasks & catalog
# --------------------------------------------------------------------------- #
@mcp.tool()
def get_task_status(api_key: str, task_id: str):
    """Look up one queued/running/finished task by its `task_id`. Returns its status
    (queued/working/completed/failed/cancelled), the function that ran, timestamps,
    any error, and `latest_print` -- the most recent progress line the task emitted.
    Poll this after queuing a pipeline task to watch it progress to completion."""
    return _get_task_status(task_id, user=_get_user(api_key))


@mcp.tool()
def get_task_history(api_key: str, limit: int = 20):
    """List this user's most recent tasks (newest first, up to `limit`), each with
    its status, function name, timestamps and latest progress line. Use it to review
    what has run or to find the task_id of a job you queued earlier."""
    return _get_task_history(user=_get_user(api_key), limit=limit)


@mcp.tool()
def get_csv_catalog(api_key: str):
    """List every CSV dataset in this user's workspace along with its columns and row
    count. Call this first to discover what data exists and which column names to
    pass to the pipeline tools."""
    return _get_csv_catalog(user_csv_root(_get_user(api_key)))


@mcp.tool()
def list_html_files(api_key: str):
    """List the rendered visualization HTML files (charts, maps) in this user's
    workspace. Pass one of these names to `display_html_file` to view it."""
    return _list_html_files(user_html_root(_get_user(api_key)))


@mcp.tool()
def get_csv_segment(api_key: str, csv_name: str, start_row: int, num_rows: int, columns: str):
    """Read a slice of a CSV: `num_rows` rows starting at `start_row` (0-based),
    limited to the comma-separated `columns`. Use it to preview or page through a
    dataset without loading the whole (potentially huge) file."""
    return _get_csv_segment(csv_name, start_row, num_rows, columns, user_csv_root(_get_user(api_key)))


@mcp.tool(name="list_pdf_folders")
def list_pdf_folders(api_key: str) -> str:
    """[Catalog] List the PDF collection folders you can chunk -- your own uploaded
    folders first, then the shared public library -- with each one's PDF count. Pass
    one or more of these names (comma-separated) to `chunk_pdfs`."""
    return _list_pdf_folders(user_pdf_root(_get_user(api_key)))


# --------------------------------------------------------------------------- #
# Synthesize -- the research-paper editor (block-model documents)
#
# A paper is a JSON block model; `build_paper` renders it into a self-contained
# interactive HTML report that lands in the user's visualizations. The tools below
# are the same code paths the browser editor uses, so anything you change here shows
# up in the user's Synthesize tab (it reloads the open paper after your turn).
# --------------------------------------------------------------------------- #
def _json_arg(value, what: str):
    """Structured tool arguments arrive as a JSON string from most model clients;
    accept either that or an already-decoded object."""
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"`{what}` must be valid JSON: {exc}") from exc


@mcp.tool(name="get_paper_schema")
def get_paper_schema() -> str:
    """[Synthesize] The block-model format of a research paper: every block type and
    its fields, the inline markup allowed, how citations and heading numbers work.
    READ THIS FIRST -- before you write or patch any paper -- so the blocks you emit
    are valid. Takes no arguments."""
    return paper_ops.PAPER_SCHEMA_DOC


@mcp.tool(name="list_papers")
def list_papers(api_key: str) -> list:
    """[Synthesize] List the user's saved research papers, each with its title,
    description and block/source counts. Start here to find the paper to work on."""
    return paper_ops.list_papers(_get_user(api_key))


@mcp.tool(name="get_paper_outline")
def get_paper_outline(api_key: str, name: str) -> dict:
    """[Synthesize] A compact map of one paper: one line per block with its INDEX,
    type, heading number and a text preview, plus the numbered source list. Use this
    to see the paper's structure and to find the index a block sits at -- those are
    the indexes `edit_paper` addresses. Much cheaper than `get_paper`."""
    return paper_ops.outline_paper(_get_user(api_key), name)


@mcp.tool(name="get_paper")
def get_paper(api_key: str, name: str) -> dict:
    """[Synthesize] The FULL block-model JSON of one paper -- every block's text.
    Use it when you need to read or rewrite actual prose; for structure alone, prefer
    the cheaper `get_paper_outline`."""
    return paper_ops.read_paper(_get_user(api_key), name)


@mcp.tool(name="edit_paper")
def edit_paper(api_key: str, name: str, ops: str) -> dict:
    """[Synthesize] Patch an existing paper with a list of surgical operations, then
    save it. This is the RIGHT way to change a paper -- it leaves everything you did
    not touch exactly as it was.

    `ops` is a JSON array; each op names a block by its index (see get_paper_outline):
      {"op":"insert",  "index":12, "block":{...}}   insert BEFORE index 12
      {"op":"replace", "index":12, "block":{...}}
      {"op":"update",  "index":12, "fields":{"caption":"..."}}   merge fields into a block
      {"op":"delete",  "index":12}
      {"op":"move",    "index":12, "to":4}
      {"op":"set_title","title":"..."}
      {"op":"add_source","source":{"authors":"...","title":"...","year":"2019"}}
      {"op":"set_sources","sources":[...]}
    Ops apply in order and indexes shift as they do, so when inserting several blocks
    work back-to-front. Call get_paper_schema for the block format. Heading numbers
    are recomputed automatically -- never write a `num`. Returns the new outline."""
    return paper_ops.edit_paper(_get_user(api_key), name, _json_arg(ops, "ops"))


@mcp.tool(name="save_paper")
def save_paper(api_key: str, name: str, doc: str, description: str = "") -> dict:
    """[Synthesize] Create a NEW paper (or overwrite an existing one wholesale) from a
    complete block-model document. `doc` is the JSON {"title","blocks","sources"} --
    call get_paper_schema for the format. To change part of a paper that already
    exists, use `edit_paper` instead: this replaces the whole document."""
    return paper_ops.write_paper(_get_user(api_key), name, _json_arg(doc, "doc"), description)


@mcp.tool(name="build_paper")
def build_paper(api_key: str, name: str, output_name: str = "") -> dict:
    """[Synthesize] Render a saved paper into a self-contained, interactive HTML report
    (its figures become live Plotly charts) and write it into the user's
    visualizations, where `list_html_files`/`display_html_file` can see it, and where
    it can even be used as a figure inside another paper. `output_name` defaults to the
    paper's name."""
    return paper_ops.build_paper(_get_user(api_key), name, output_name)


# --------------------------------------------------------------------------- #
# Studio -- the visual pipeline canvas
# --------------------------------------------------------------------------- #
@mcp.tool(name="get_studio_manifest")
def get_studio_manifest() -> dict:
    """[Studio] The vocabulary for building a pipeline: how the graph format and its
    csv/column wires work, plus every node the canvas offers with its category, input
    ports (in order) and parameters. READ THIS before writing or running a graph.
    Takes no arguments."""
    return studio_ops.manifest_summary()


@mcp.tool(name="list_studio_pipelines")
def list_studio_pipelines(api_key: str) -> list:
    """[Studio] List the user's saved Studio pipelines (the canvas's Templates
    dropdown), each with its description, node count and the actions it runs."""
    return studio_ops.list_graphs(_get_user(api_key))


@mcp.tool(name="get_studio_pipeline")
def get_studio_pipeline(api_key: str, name: str) -> dict:
    """[Studio] Read one saved pipeline as a {nodes, edges} graph -- what it does, how
    it is wired, and which parameters each node uses."""
    return studio_ops.read_graph(_get_user(api_key), name)


@mcp.tool(name="save_studio_pipeline")
def save_studio_pipeline(api_key: str, name: str, graph: str, description: str = "") -> dict:
    """[Studio] Save a pipeline the user can then open on the Studio canvas. `graph` is
    the JSON {"nodes":[{"id","action","csv","column","fields"}], "edges":[{"from","to",
    "toPort"}]} -- see get_studio_manifest for the actions, ports and wiring rules.
    This only saves it; call `run_studio_pipeline` to actually execute it."""
    data = _json_arg(graph, "graph")
    return studio_ops.write_graph(_get_user(api_key), name, data.get("nodes", []),
                                  data.get("edges", []), description)


@mcp.tool(name="run_studio_pipeline")
def run_studio_pipeline(api_key: str, name: str = "", graph: str = "") -> dict:
    """[Studio] Run a pipeline: every node is queued as a background task in dependency
    order (exactly what the canvas's Run button does). Pass either `name` (a saved
    pipeline) or an inline `graph` (the same JSON as save_studio_pipeline). Returns one
    task_id per queued node -- poll them with get_task_status."""
    user = _get_user(api_key)
    if name:
        data = studio_ops.read_graph(user, name)
    elif graph:
        data = _json_arg(graph, "graph")
    else:
        raise ValueError("Pass either `name` (a saved pipeline) or an inline `graph`.")
    tasks = studio_ops.queue_graph(user, data.get("nodes", []), data.get("edges", []),
                                   blocks=data.get("blocks") or {})
    return {"queued": len(tasks), "tasks": tasks}


# --------------------------------------------------------------------------- #
# The HTML viewer app
# --------------------------------------------------------------------------- #
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
    html_root = str(user_html_root(_get_user(api_key)))
    filepath = os.path.join(html_root, filename)
    if not os.path.abspath(filepath).startswith(os.path.abspath(html_root)):
        return "<h1>Error: Invalid file path</h1>"
    if not os.path.isfile(filepath):
        return f"<h1>Error: {filename} not found</h1>"
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()
