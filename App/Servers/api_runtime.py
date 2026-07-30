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

from App.Frontend.portal import paper_ops, studio_ops
from App.Frontend.portal.services import resolve_api_key
from App.Frontend.portal.task_engine import get_task_status, queue_user_task
from App.Frontend.webapp.storage import user_csv_root, user_paper_root, user_pdf_root, user_template_root
from App.Servers.pipeline_tools import ROOT_BUILDERS, queue_from_api, register_api_routes

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
        "live progress line) to follow it to completion. Pipeline functions fall into "
        "four families: Import (fetch raw data), Annotation (add a column in place), "
        "Distillation (write a new derived CSV) and Visualization (render an HTML "
        "chart).\n\n"
        "Two further families act on the platform's other two tabs, synchronously: "
        "**Studio** reads, authors and runs the visual node pipelines, and "
        "**Synthesize** reads, patches and builds the block-model research papers "
        "whose figures are the caller's own live charts (start at /api/papers/schema "
        "and /api/studio/manifest -- they document those formats)."
    ),
)


def _current_user(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header.")
    api_key = resolve_api_key(x_api_key)
    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return api_key.user


CurrentUser = Depends(_current_user)

# --------------------------------------------------------------------------- #
# The pipeline endpoints (Import / Annotation / Distillation / Visualization).
#
# One POST per function in App.Backend.registry, generated from that registry: it
# already holds each function's arguments, defaults, storage roots and documentation,
# so restating all of it here as ~35 request models and ~35 near-identical handlers
# only created a second copy to keep in step. Adding a pipeline function to the
# platform now means adding one registry entry; its endpoint appears here for free.
# --------------------------------------------------------------------------- #
register_api_routes(app, queue_from_api(queue_user_task, ROOT_BUILDERS), CurrentUser)


# --------------------------------------------------------------------------- #
# Tasks & catalog
# --------------------------------------------------------------------------- #
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
    return "\n\n".join(_list_html_files(root) for root in (user_template_root(user), user_paper_root(user)))


@app.get(
    "/api/catalog/list-pdf-folders",
    tags=["Catalog"],
    summary="List the caller's PDF collections",
    description="List the PDF collection folders the caller can chunk -- their own uploaded folders plus the shared public library. Pass one or more of these names (comma-separated) to /api/pipeline/chunk-pdfs.",
)
def list_pdf_folders(user=CurrentUser):
    return _list_pdf_folders(user_pdf_root(user))


@app.get(
    "/api/data/get-csv-segment",
    tags=["Catalog"],
    summary="Read a slice of a CSV dataset",
    description="Read `num_rows` rows starting at `start_row` (0-based) from `csv_name`, limited to the comma-separated `columns`. Preview or page through a dataset without loading the whole file.",
)
def get_csv_segment(csv_name: str, start_row: int, num_rows: int, columns: str, user=CurrentUser):
    return _get_csv_segment(csv_name, start_row, num_rows, columns, user_csv_root(user))


# --------------------------------------------------------------------------- #
# Synthesize -- authoring research papers from the caller's own charts
# --------------------------------------------------------------------------- #
class SavePaperRequest(BaseModel):
    doc: dict          # the block model: {"title", "blocks": [...], "sources": [...]}
    description: str = ""


class EditPaperRequest(BaseModel):
    ops: list[dict]    # [{"op": "insert"|"replace"|"update"|"delete"|"move"|…, "index": int, …}]


class BuildPaperRequest(BaseModel):
    output_name: str = ""   # defaults to the paper's own name
    description: str = ""


class SavePipelineRequest(BaseModel):
    nodes: list[dict]  # [{"id", "action", "csv", "column", "fields": {...}}]
    edges: list[dict]  # [{"from", "to", "toPort"}]
    description: str = ""


class RunPipelineRequest(BaseModel):
    name: str = ""     # a saved pipeline, OR an inline graph below
    nodes: list[dict] = []
    edges: list[dict] = []


def _paper(call):
    """Run a paper/studio operation, turning its errors into clean 400s."""
    try:
        return call()
    except (paper_ops.PaperError, studio_ops.StudioError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get(
    "/api/papers/schema",
    tags=["Synthesize"],
    summary="The research-paper block model (read this before writing a paper)",
    description=(
        "Return the block-model format of a Synthesize research paper: every block "
        "type and its fields, the inline markup allowed, and how citations and "
        "automatic heading numbers work. Read this before creating or patching a "
        "paper so the blocks you send are valid."
    ),
)
def paper_schema():
    return {"schema": paper_ops.PAPER_SCHEMA_DOC}


@app.get(
    "/api/papers",
    tags=["Synthesize"],
    summary="List the caller's research papers",
    description="List the caller's saved papers, each with its title, description and block/source counts.",
)
def api_list_papers(user=CurrentUser):
    return _paper(lambda: paper_ops.list_papers(user))


@app.get(
    "/api/papers/{name}/outline",
    tags=["Synthesize"],
    summary="Outline one paper (block indexes + previews)",
    description=(
        "A compact map of the paper: one line per block with its INDEX, type, heading "
        "number and a text preview, plus the numbered source list. These indexes are "
        "the ones PATCH /api/papers/{name} addresses. Much cheaper than fetching the "
        "whole document."
    ),
)
def api_paper_outline(name: str, user=CurrentUser):
    return _paper(lambda: paper_ops.outline_paper(user, name))


@app.get(
    "/api/papers/{name}",
    tags=["Synthesize"],
    summary="Read one paper's full block model",
    description="The complete block-model JSON of a paper -- every block's text. For structure alone, prefer the outline endpoint.",
)
def api_get_paper(name: str, user=CurrentUser):
    return _paper(lambda: paper_ops.read_paper(user, name))


@app.put(
    "/api/papers/{name}",
    tags=["Synthesize"],
    summary="Create or overwrite a paper",
    description=(
        "Write a complete block-model document, creating the paper or replacing it "
        "wholesale. To change part of an existing paper, use PATCH instead. See "
        "/api/papers/schema for the block format; heading numbers are assigned "
        "automatically, so never send a `num`."
    ),
)
def api_save_paper(name: str, data: SavePaperRequest, user=CurrentUser):
    return _paper(lambda: paper_ops.write_paper(user, name, data.doc, data.description))


@app.patch(
    "/api/papers/{name}",
    tags=["Synthesize"],
    summary="Patch a paper with surgical block operations",
    description=(
        "Apply an ordered list of operations to an existing paper and save it, leaving "
        "everything else untouched. Each op addresses a block by the index the outline "
        "reports: {op:insert|replace|update|delete|move, index, block|fields|to}, plus "
        "set_title, add_source and set_sources. Ops apply in order and indexes shift as "
        "they do, so insert back-to-front. Returns the resulting outline."
    ),
)
def api_edit_paper(name: str, data: EditPaperRequest, user=CurrentUser):
    return _paper(lambda: paper_ops.edit_paper(user, name, data.ops))


@app.post(
    "/api/papers/{name}/build",
    tags=["Synthesize"],
    summary="Build a paper into an interactive HTML report",
    description=(
        "Render a saved paper into a self-contained, interactive HTML report -- each "
        "figure becomes a live Plotly chart -- and write it into the caller's "
        "visualizations, where it can be viewed, published, downloaded, or used as a "
        "figure inside another paper. `output_name` defaults to the paper's name."
    ),
)
def api_build_paper(name: str, data: BuildPaperRequest, user=CurrentUser):
    return _paper(lambda: paper_ops.build_paper(user, name, data.output_name, data.description))


# --------------------------------------------------------------------------- #
# Studio -- the visual pipeline canvas
# --------------------------------------------------------------------------- #
@app.get(
    "/api/studio/manifest",
    tags=["Studio"],
    summary="The Studio node catalog and graph format",
    description=(
        "The vocabulary for building a pipeline: how the {nodes, edges} graph format "
        "and its csv/column wires work, plus every node the canvas offers with its "
        "category, input ports (in port order) and parameters. Read this before "
        "writing or running a graph."
    ),
)
def api_studio_manifest():
    return studio_ops.manifest_summary()


@app.get(
    "/api/studio/pipelines",
    tags=["Studio"],
    summary="List the caller's saved pipelines",
    description="List the caller's saved Studio pipelines (the canvas's Templates dropdown), each with its description, node count and actions.",
)
def api_list_pipelines(user=CurrentUser):
    return _paper(lambda: studio_ops.list_graphs(user))


@app.get(
    "/api/studio/pipelines/{name}",
    tags=["Studio"],
    summary="Read one saved pipeline as a graph",
    description="Return a saved pipeline as a {nodes, edges} graph: what it does, how it is wired, and each node's parameters.",
)
def api_get_pipeline(name: str, user=CurrentUser):
    return _paper(lambda: studio_ops.read_graph(user, name))


@app.put(
    "/api/studio/pipelines/{name}",
    tags=["Studio"],
    summary="Save a pipeline the user can open on the canvas",
    description=(
        "Save a {nodes, edges} graph as a Studio pipeline, so it appears in the "
        "canvas's Templates dropdown and can be opened and edited visually. See "
        "/api/studio/manifest for the actions, ports and wiring rules. This only "
        "saves it -- POST .../run to execute it."
    ),
)
def api_save_pipeline(name: str, data: SavePipelineRequest, user=CurrentUser):
    return _paper(lambda: studio_ops.write_graph(user, name, data.nodes, data.edges, data.description))


@app.post(
    "/api/studio/run",
    tags=["Studio"],
    summary="Run a pipeline (queues every node in dependency order)",
    description=(
        "Compile a pipeline into background tasks and queue them in topological order "
        "-- exactly what the canvas's Run button does. Pass either `name` (a saved "
        "pipeline) or an inline `nodes`/`edges` graph. Returns one task_id per queued "
        "node; poll them with /api/task/status/{task_id}."
    ),
)
def api_run_pipeline(data: RunPipelineRequest, user=CurrentUser):
    def run():
        if data.name:
            graph = studio_ops.read_graph(user, data.name)
            nodes, edges = graph["nodes"], graph["edges"]
        else:
            nodes, edges = data.nodes, data.edges
        if not nodes:
            raise studio_ops.StudioError("Pass either `name` (a saved pipeline) or a `nodes`/`edges` graph.")
        tasks = studio_ops.queue_graph(user, nodes, edges)
        return {"queued": len(tasks), "tasks": tasks}

    return _paper(run)
