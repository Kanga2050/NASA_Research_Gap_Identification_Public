"""Studio (visual-scripting) operations, shared by the Django view, the REST API and MCP.

The Studio canvas is a Drawflow graph, but Drawflow's export format is an editor
detail (DOM classes, port objects, pixel positions). Everything here speaks a
**simple graph** instead -- the same shape the browser already POSTs to Run:

    {"nodes": [{"id": "1", "action": "embed_text", "csv": "", "column": "",
                "fields": {"text_column": "text"}}, ...],
     "edges": [{"from": "1", "to": "2", "toPort": 0}, ...]}

``queue_graph`` compiles that into background tasks (this is the code the Run
button runs), and ``to_drawflow``/``from_drawflow`` convert between it and what
the canvas loads, so an agent can *write a graph the user can then open in the
Studio* without ever knowing Drawflow exists.
"""
from __future__ import annotations

import json
from collections import deque

from .file_meta import get_description, set_description
from .graph_manifest import MANIFEST, PALETTE
from .output_preview import resolve_safe_path
from .paper_ops import safe_name
from App.Frontend.webapp.storage import user_template_root

# The Studio's own wiring rules, restated for an agent that has never seen the UI.
STUDIO_GRAPH_DOC = """\
A Studio pipeline is a directed graph of nodes joined by wires:

  {"nodes": [{"id": str, "action": str, "csv": str, "column": str, "fields": {param: value}}],
   "edges": [{"from": node_id, "to": node_id, "toPort": int}]}

`action` is one of the actions from get_studio_manifest. `toPort` is the 0-based
index of the input on the RECEIVING node (the manifest lists each node's inputs in
port order). `fields` sets that node's parameters (the manifest's `prefs`, plus the
`output` param that names what it produces).

There are two kinds of wire:
  * a **csv** wire carries a whole table;
  * a **column** wire carries one column (and remembers which table it came from).

Two special nodes start every pipeline:
  {"action": "__csv__",    "csv": "Space_Biology"}   -> emits a csv wire for that table
  {"action": "__column__", "column": "text"}         -> takes a csv wire in, emits that column

The rest follow their category:
  annotation   — takes column wire(s), adds a new column to the SAME table, and emits
                 that new column as a wire.
  distillation — takes csv/column wires, writes a NEW table, and emits it as a csv wire.
  visualization— takes column wire(s) and renders an HTML chart (terminal; no output wire).

A node's source table is inferred from its input wires -- you never pass a table name
to anything but __csv__. Example: chart the topic sizes of Space_Biology:

  nodes: 1 __csv__ (csv=Space_Biology) -> 2 __column__ (column=Topic_Label)
         -> 3 bar_chart (fields: {output_name: "Topic_Sizes", top_n: 20})
  edges: 1->2 port 0, 2->3 port 0
"""


class StudioError(ValueError):
    """A graph could not be compiled, saved or run."""


# --------------------------------------------------------------------------- #
# The manifest, summarized for an agent
# --------------------------------------------------------------------------- #
def manifest_summary() -> dict:
    """Every node the Studio can place: its category, its input ports (in order),
    its parameters and what it outputs. This is the vocabulary for building a graph."""
    nodes = []
    for action, entry in MANIFEST.items():
        nodes.append({
            "action": action,
            "label": entry["label"],
            "category": entry["category"],
            "inputs": [
                {"port": i, "param": inp["param"], "label": inp["label"], "wire": inp["wire"],
                 "accepts": inp.get("accepts", []), "optional": inp.get("optional", False)}
                for i, inp in enumerate(entry["inputs"])
            ],
            "fields": [
                {"param": p["param"], "label": p["label"], "type": p["widget"],
                 "default": p["default"], "options": p["options"]}
                for p in entry["prefs"]
            ],
            "output": {"param": entry["output"].get("param"),
                       "kind": entry["output"].get("kind"),
                       "default": entry["output"].get("default")},
        })
    return {"how_it_works": STUDIO_GRAPH_DOC,
            "palette": PALETTE,
            "nodes": nodes}


# --------------------------------------------------------------------------- #
# Compile + queue (this is what the Run button does)
# --------------------------------------------------------------------------- #
def _topo_sort(node_ids, edges):
    """Kahn topological sort over the wires. Returns an ordered list of node ids,
    or None if the graph contains a cycle."""
    indeg = {nid: 0 for nid in node_ids}
    adj = {nid: [] for nid in node_ids}
    for edge in edges:
        src, dst = str(edge.get("from")), str(edge.get("to"))
        if src in indeg and dst in indeg:
            adj[src].append(dst)
            indeg[dst] += 1
    queue = deque(nid for nid in node_ids if indeg[nid] == 0)
    order = []
    while queue:
        nid = queue.popleft()
        order.append(nid)
        for nxt in adj[nid]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    return order if len(order) == len(node_ids) else None


def _coerce_number(value):
    """Studio sends form values as strings; turn numeric-widget values back into
    int/float so backend functions (e.g. bins, top_n) get real numbers."""
    text = str(value).strip()
    if text == "":
        return value
    try:
        return float(text) if ("." in text or "e" in text.lower()) else int(text)
    except ValueError:
        return value


def _queue_action(user, action: str, cleaned: dict):
    """Queue one node's backend function with the args the compiler resolved.

    Imported lazily: `views` owns TASK_SPECS (the positional-arg contract every
    caller shares) and imports this module, so a top-level import would cycle.
    """
    from .views import _queue_task_for_user

    return _queue_task_for_user(user, action, cleaned)


def queue_graph(user, nodes: list, edges: list, queue_fn=None) -> list[dict]:
    """Compile a simple graph into queued tasks, in dependency (topological) order.

    Wires carry "carriage": a csv wire carries a table name, a column wire carries
    {csv, column}. We propagate carriage through the graph in topological order to
    resolve each function's source CSV and column args, then queue it. Per-user FIFO
    execution in the task engine means enqueuing in topological order is sufficient
    for correct execution order. Source/bridge nodes (__csv__, __column__) queue
    nothing. Returns one {task_id, action, category, output_name} per queued node.

    ``queue_fn(user, action, cleaned) -> {"task_id": ...}`` is injectable so the
    Django view can keep using its own form-validating queue path.
    """
    queue_fn = queue_fn or _queue_action
    by_id = {str(n.get("id")): n for n in nodes}

    order = _topo_sort(list(by_id), edges)
    if order is None:
        raise StudioError("The pipeline has a cycle -- remove a connection.")

    # incoming[node] = list of (source_node, target_input_port_index)
    incoming = {nid: [] for nid in by_id}
    for edge in edges:
        src, dst = str(edge.get("from")), str(edge.get("to"))
        if dst in incoming and src in by_id:
            incoming[dst].append((src, int(edge.get("toPort", 0))))

    carry = {}  # node id -> its output carriage: {"wire","csv"[,"column"]}
    queued = []
    for nid in order:
        node = by_id[nid]
        entry = MANIFEST.get(node.get("action"))
        if entry is None:
            continue
        in_by_port = {port: carry.get(src) for src, port in incoming.get(nid, [])}

        if entry["special"] == "csv_input":
            carry[nid] = {"wire": "csv", "csv": node.get("csv", "")}
            continue
        if entry["special"] == "select_column":
            src = in_by_port.get(0) or {}
            carry[nid] = {"wire": "column", "csv": src.get("csv", ""),
                          "column": node.get("column", "")}
            continue

        cleaned = dict(node.get("fields") or {})
        for pref in entry["prefs"]:
            if pref["widget"] == "number" and pref["param"] in cleaned:
                cleaned[pref["param"]] = _coerce_number(cleaned[pref["param"]])

        source_csv, csv_inputs = "", []
        for i, inp in enumerate(entry["inputs"]):
            wire = in_by_port.get(i)
            if not wire:
                continue
            if inp["wire"] == "csv":
                csv_inputs.append(wire.get("csv", ""))
                source_csv = source_csv or wire.get("csv", "")
            else:  # a column wire: its column name is the arg; its CSV seeds the source
                cleaned[inp["param"]] = wire.get("column", "")
                source_csv = source_csv or wire.get("csv", "")

        if entry["table_param"]:
            cleaned[entry["table_param"]] = source_csv or cleaned.get(entry["table_param"], "")
        if node.get("action") == "combine_csvs":
            cleaned["source_csvs"] = ",".join(c for c in csv_inputs if c)

        result = queue_fn(user, node["action"], cleaned)

        out = entry["output"]
        out_name = cleaned.get(out["param"]) or out.get("default", "")
        if entry["category"] == "annotation":
            carry[nid] = {"wire": "column", "csv": source_csv, "column": out_name}
        elif entry["category"] == "distillation":
            carry[nid] = {"wire": "csv", "csv": out_name}
        else:
            carry[nid] = {"wire": "none"}

        queued.append({"task_id": result["task_id"], "action": node["action"],
                       "category": entry["category"], "output_name": out_name})
    return queued


# --------------------------------------------------------------------------- #
# Simple graph <-> Drawflow (what the canvas saves and loads)
# --------------------------------------------------------------------------- #
def _drawflow_nodes(graph: dict) -> dict:
    try:
        return graph["drawflow"]["Home"]["data"]
    except (KeyError, TypeError):
        return {}


def from_drawflow(graph: dict) -> dict:
    """Drawflow export -> the simple {nodes, edges} graph."""
    nodes, edges = [], []
    for nid, node in _drawflow_nodes(graph).items():
        data = node.get("data") or {}
        nodes.append({"id": str(nid), "action": node.get("name", ""),
                      "csv": data.get("csv", ""), "column": data.get("column", ""),
                      "fields": data.get("fields") or {}})
        for port, spec in (node.get("inputs") or {}).items():
            try:
                to_port = int(str(port).split("_")[1]) - 1
            except (IndexError, ValueError):
                continue
            for conn in spec.get("connections") or []:
                edges.append({"from": str(conn.get("node")), "to": str(nid), "toPort": to_port})
    return {"nodes": nodes, "edges": edges}


def to_drawflow(nodes: list, edges: list) -> dict:
    """The simple {nodes, edges} graph -> a Drawflow export the canvas can import.

    Node HTML/positions are regenerated: studio.js re-renders every node's widgets
    from its `data` after an import, so we only have to emit the shell it expects
    (class, category-tagged div, port objects) and lay the nodes out left-to-right
    in topological order so the imported graph is readable.
    """
    by_id = {str(n.get("id")): n for n in nodes}
    for nid, node in by_id.items():
        if node.get("action") not in MANIFEST:
            raise StudioError(
                f"Node {nid}: unknown action {node.get('action')!r}. "
                "Call get_studio_manifest for the list of actions."
            )

    order = _topo_sort(list(by_id), edges) or list(by_id)
    depth = {}
    for nid in order:
        parents = [str(e["from"]) for e in edges if str(e.get("to")) == nid and str(e.get("from")) in by_id]
        depth[nid] = max((depth.get(p, 0) + 1 for p in parents), default=0)
    row = {}

    data = {}
    for nid in order:
        node = by_id[nid]
        entry = MANIFEST[node["action"]]
        col = depth[nid]
        row[col] = row.get(col, -1) + 1
        fields = dict(node.get("fields") or {})
        for pref in entry["prefs"]:                     # fill unset params with defaults
            fields.setdefault(pref["param"], pref["default"])
        if entry["output"].get("param"):
            fields.setdefault(entry["output"]["param"], entry["output"]["default"])

        inputs = {f"input_{i + 1}": {"connections": []} for i in range(len(entry["inputs"]))}
        outputs = {} if entry["category"] == "visualization" else {"output_1": {"connections": []}}
        data[str(nid)] = {
            "id": int(nid) if str(nid).isdigit() else nid,
            "name": node["action"],
            "data": {"action": node["action"], "csv": node.get("csv", ""),
                     "column": node.get("column", ""), "fields": fields},
            "class": "studio-node-wrap",
            "html": f'<div class="studio-node" data-cat="{entry["category"]}"></div>',
            "typenode": False,
            "inputs": inputs,
            "outputs": outputs,
            "pos_x": 60 + col * 320,
            "pos_y": 60 + row[col] * 190,
        }

    for edge in edges:
        src, dst = str(edge.get("from")), str(edge.get("to"))
        if src not in data or dst not in data:
            raise StudioError(f"Edge {src}->{dst} refers to a node that does not exist.")
        port = int(edge.get("toPort", 0))
        in_key, out_key = f"input_{port + 1}", "output_1"
        if in_key not in data[dst]["inputs"]:
            raise StudioError(
                f"Node {dst} ({data[dst]['name']}) has no input port {port}. "
                "Ports are 0-based; see the node's `inputs` in get_studio_manifest."
            )
        if out_key not in data[src]["outputs"]:
            raise StudioError(f"Node {src} ({data[src]['name']}) is terminal and emits no wire.")
        data[dst]["inputs"][in_key]["connections"].append({"node": src, "input": out_key})
        data[src]["outputs"][out_key]["connections"].append({"node": dst, "output": in_key})

    return {"drawflow": {"Home": {"data": data}}}


# --------------------------------------------------------------------------- #
# Saved graphs (Studio "templates")
# --------------------------------------------------------------------------- #
def graph_path(user, name: str):
    stem = safe_name(name)
    path = resolve_safe_path(user_template_root(user), stem, ".json") if stem else None
    if path is None:
        raise StudioError(f"Invalid pipeline name: {name!r}")
    return path


def list_graphs(user) -> list[dict]:
    """The user's saved Studio pipelines (what the canvas's Templates dropdown lists)."""
    root = user_template_root(user)
    out = []
    for path in sorted(root.glob("*.json")):
        if path.stem.startswith("_descriptions"):
            continue
        try:
            simple = from_drawflow(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            continue
        out.append({"name": path.stem, "description": get_description(root, path.stem),
                    "nodes": len(simple["nodes"]),
                    "actions": [n["action"] for n in simple["nodes"]]})
    return out


def read_graph(user, name: str) -> dict:
    """A saved pipeline as the simple {nodes, edges} graph."""
    path = graph_path(user, name)
    if not path.exists():
        raise StudioError(f"No pipeline named {name!r}. Call list_studio_pipelines to see what exists.")
    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise StudioError(f"Pipeline {name!r} is corrupt: {exc}") from exc
    simple = from_drawflow(graph)
    return {"name": path.stem, "description": get_description(user_template_root(user), path.stem),
            **simple}


def write_graph(user, name: str, nodes: list, edges: list, description: str = "") -> dict:
    """Save a simple graph as a Studio pipeline the user can open on the canvas."""
    path = graph_path(user, name)
    graph = to_drawflow(nodes, edges)
    path.write_text(json.dumps(graph), encoding="utf-8")
    if description:
        set_description(user_template_root(user), path.stem, description)
    return {"ok": True, "name": path.stem, "nodes": len(nodes),
            "note": f"“{path.stem}” now appears in the Studio's Templates dropdown."}
