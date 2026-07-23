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

from . import block_ops
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


ANY_WIRE = ("text", "number", "date", "embedding")


class StudioError(ValueError):
    """A graph could not be compiled, saved or run."""


def entry_for(node: dict, blocks: dict | None = None) -> dict:
    """The manifest entry for a node -- or, for a block instance, one synthesised from
    the block's own interface, so the rest of the compiler treats a composite exactly
    like any other node."""
    action = node.get("action", "")
    if not block_ops.is_instance(action):
        entry = MANIFEST.get(action)
        if entry is None:
            raise StudioError(
                f"Unknown action {action!r}. Call get_studio_manifest for the list of actions.")
        return entry
    name = block_ops.instance_block(action)
    block = (blocks or {}).get(name)
    if not block:
        raise StudioError(f"This pipeline uses block {name!r} but carries no definition for it.")
    header = block["header"]
    return {
        "action": action, "label": name, "category": "block", "table_param": None,
        "inputs": [{"param": f"__in_{p['port']}__", "label": p["name"],
                    "wire": p.get("wire", "any"), "accepts": list(p.get("accepts") or []),
                    "optional": False} for p in header["inputs"]],
        # One promoted name may drive several inner parameters (a query used by both a
        # keyword and a semantic score); the instance shows one field for it.
        "prefs": list({p["name"]: {"param": p["name"], "label": p["name"], "widget": "text",
                                   "default": p.get("default", ""), "options": []}
                       for p in header["params"]}.values()),
        "output": {"param": None, "kind": "block", "default": ""},
        "outputs": header["outputs"],
        "special": "block_instance", "projects": None, "variadic": None,
    }


def output_port_count(entry: dict, node: dict) -> int:
    """How many output ports this node instance has. One for most nodes; none for a
    chart or a Block Outputs boundary; one per declared output for a block instance;
    and a Block Inputs boundary has one per block input."""
    if entry.get("special") == "block_instance":
        return max(1, len(entry.get("outputs") or []))
    if entry.get("special") == "block_in":
        try:
            return max(1, int(node.get("ports_out") or 1))
        except (TypeError, ValueError):
            return 1
    if entry["output"].get("kind") in (None, "html"):
        return 0
    return 1


def input_specs(entry: dict, node: dict) -> list[dict]:
    """The input ports of one node *instance*, in port order.

    Most nodes have exactly the ports the manifest declares. A variadic node (today,
    Combine CSVs) lets the canvas add and remove ports, so the instance carries its own
    count in ``ports`` and everything past the declared list repeats the variadic spec.
    """
    specs = list(entry["inputs"])
    var = entry.get("variadic")
    if var and var.get("side") == "output":
        return []                          # its ports are outputs, not inputs
    if not var:
        return specs
    try:
        count = int(node.get("ports") or len(specs))
    except (TypeError, ValueError):
        count = len(specs)
    count = max(int(var.get("min", len(specs))), min(count, int(var.get("max", 12))))
    while len(specs) < count:
        specs.append({"param": f"__{var['wire']}_{len(specs) + 1}__",
                      "label": f"{var['label']} {len(specs) + 1}", "wire": var["wire"],
                      "accepts": list(var.get("accepts") or ANY_WIRE), "optional": True})
    return specs[:count]


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
            "variadic": entry.get("variadic"),
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


def queue_graph(user, nodes: list, edges: list, queue_fn=None, blocks: dict | None = None) -> list[dict]:
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
    # Blocks are notation: inline every instance (and drop the definition regions, which
    # are a picture of a block rather than a step of this pipeline) before anything is
    # queued, so what runs is always plain nodes.
    nodes, edges = block_ops.expand(nodes, edges, blocks or {})
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
        # A schema definition opened flat carries its boundary markers; they run nothing
        # (a bare definition is normally inlined by expand, but a user can also open one to
        # edit it and hit Run). Skip them rather than trying to queue a non-existent task.
        if entry["special"] in ("block_in", "block_out"):
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
        for i, inp in enumerate(input_specs(entry, node)):
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
        elif out["kind"] == "csv":
            # a distillation's new table, or an importer's freshly written one -- an
            # importer is a source node, but it still emits the CSV it just wrote, so
            # a pipeline can start from the harvest rather than from an existing table
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
                      "ports": len(node.get("inputs") or {}),
                      "ports_out": len(node.get("outputs") or {}),
                      "def_of": data.get("def_of") or None,
                      "fields": data.get("fields") or {}})
        for port, spec in (node.get("inputs") or {}).items():
            try:
                to_port = int(str(port).split("_")[1]) - 1
            except (IndexError, ValueError):
                continue
            for conn in spec.get("connections") or []:
                try:
                    from_port = int(str(conn.get("input", "output_1")).split("_")[1]) - 1
                except (IndexError, ValueError):
                    from_port = 0
                edges.append({"from": str(conn.get("node")), "to": str(nid),
                              "toPort": to_port, "fromPort": from_port})
    return {"nodes": nodes, "edges": edges}


def to_drawflow(nodes: list, edges: list, blocks: dict | None = None) -> dict:
    """The simple {nodes, edges} graph -> a Drawflow export the canvas can import.

    Node HTML/positions are regenerated: studio.js re-renders every node's widgets
    from its `data` after an import, so we only have to emit the shell it expects
    (class, category-tagged div, port objects) and lay the nodes out left-to-right
    in topological order so the imported graph is readable.
    """
    by_id = {str(n.get("id")): n for n in nodes}
    entries = {nid: entry_for(node, blocks) for nid, node in by_id.items()}

    order = _topo_sort(list(by_id), edges) or list(by_id)
    depth = {}
    for nid in order:
        parents = [str(e["from"]) for e in edges if str(e.get("to")) == nid and str(e.get("from")) in by_id]
        depth[nid] = max((depth.get(p, 0) + 1 for p in parents), default=0)
    # A chart is where a pipeline ends, so it belongs in the last column whatever its
    # own depth -- otherwise a chart fed by a short branch lands mid-canvas, reading as
    # if the longer branches beside it flowed past the end of the pipeline.
    last = max(depth.values(), default=0)
    for nid in order:
        if entries[nid]["category"] == "visualization":
            depth[nid] = last
    row = {}

    data = {}
    for nid in order:
        node = by_id[nid]
        entry = entries[nid]
        col = depth[nid]
        row[col] = row.get(col, -1) + 1
        fields = dict(node.get("fields") or {})
        for pref in entry["prefs"]:                     # fill unset params with defaults
            fields.setdefault(pref["param"], pref["default"])
        if entry["output"].get("param"):
            fields.setdefault(entry["output"]["param"], entry["output"]["default"])

        inputs = {f"input_{i + 1}": {"connections": []}
                  for i in range(len(input_specs(entry, node)))}
        outputs = {f"output_{i + 1}": {"connections": []}
                   for i in range(output_port_count(entry, node))}
        node_data = {"action": node["action"], "csv": node.get("csv", ""),
                     "column": node.get("column", ""), "fields": fields}
        if node.get("def_of"):
            node_data["def_of"] = node["def_of"]      # part of a definition region
        data[str(nid)] = {
            "id": int(nid) if str(nid).isdigit() else nid,
            "name": node["action"],
            "data": node_data,
            "class": "studio-node-wrap",
            "html": f'<div class="studio-node" data-cat="{entry["category"]}"></div>',
            "typenode": False,
            "inputs": inputs,
            "outputs": outputs,
            "pos_x": 60 + col * 320,
            "pos_y": 60 + row[col] * 190,
        }

    # Definition regions are a picture of a block, not a step of the pipeline, so they
    # get their own band underneath it -- one band per block, in a stable order.
    pipeline_bottom = max((n["pos_y"] for nid, n in data.items()
                           if not by_id[nid].get("def_of")), default=0)
    band_top = pipeline_bottom + 300
    for block_name in dict.fromkeys(n.get("def_of") for n in by_id.values() if n.get("def_of")):
        members = [nid for nid in order if by_id[nid].get("def_of") == block_name]
        if not members:
            continue
        top = min(data[nid]["pos_y"] for nid in members)
        left = min(data[nid]["pos_x"] for nid in members)
        for nid in members:
            data[nid]["pos_y"] += band_top - top
            data[nid]["pos_x"] += 60 - left
        band_top = max(data[nid]["pos_y"] for nid in members) + 300

    for edge in edges:
        src, dst = str(edge.get("from")), str(edge.get("to"))
        if src not in data or dst not in data:
            raise StudioError(f"Edge {src}->{dst} refers to a node that does not exist.")
        port, out_port = int(edge.get("toPort", 0)), int(edge.get("fromPort", 0))
        in_key, out_key = f"input_{port + 1}", f"output_{out_port + 1}"
        if in_key not in data[dst]["inputs"]:
            raise StudioError(
                f"Node {dst} ({data[dst]['name']}) has no input port {port}. "
                "Ports are 0-based; see the node's `inputs` in get_studio_manifest."
            )
        if out_key not in data[src]["outputs"]:
            raise StudioError(
                f"Node {src} ({data[src]['name']}) has no output port {out_port}."
                if out_port else
                f"Node {src} ({data[src]['name']}) is terminal and emits no wire.")
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
    """The user's saved Studio graphs -- pipelines and blocks, tagged by kind so the
    canvas can list them in separate sections (a block is inserted into a pipeline;
    a pipeline is opened)."""
    root = user_template_root(user)
    out = []
    for path in sorted(root.rglob("*.json")):        # templates may live in nested folders
        if path.stem.startswith("_descriptions"):
            continue
        folder = path.parent.relative_to(root).as_posix()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            simple = from_drawflow(raw)
        except (ValueError, OSError):
            continue
        header = raw.get("block") if isinstance(raw, dict) else None
        out.append({"name": path.stem, "description": get_description(path.parent, path.stem),
                    "folder": "" if folder == "." else folder,
                    "kind": "block" if header else "pipeline",
                    "version": (header or {}).get("version", 1),
                    "ports": {"inputs": [p["name"] for p in (header or {}).get("inputs", [])],
                              "outputs": [p["name"] for p in (header or {}).get("outputs", [])],
                              "params": [p["name"] for p in (header or {}).get("params", [])]}
                    if header else None,
                    "uses": sorted((raw.get("blocks") or {}).keys()) if isinstance(raw, dict) else [],
                    "nodes": len(simple["nodes"]),
                    "actions": [n["action"] for n in simple["nodes"]]})
    return out


def block_library(user) -> dict:
    """Every block template the user has, by name -> current version."""
    return {g["name"]: g["version"] for g in list_graphs(user) if g["kind"] == "block"}


def _embedded_blocks(raw: dict) -> dict:
    """The frozen block definitions a saved pipeline carries."""
    blocks = {}
    for name, entry in (raw.get("blocks") or {}).items():
        blocks[name] = {"header": entry["header"], "body": entry["body"]}
    return blocks


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
    blocks = _embedded_blocks(graph)
    return {"name": path.stem, "description": get_description(user_template_root(user), path.stem),
            "block": graph.get("block"), "blocks": blocks,
            "stale": block_ops.stale_blocks(blocks, block_library(user)),
            **simple}


def write_graph(user, name: str, nodes: list, edges: list, description: str = "",
                blocks: dict | None = None, is_block: bool = False) -> dict:
    """Save a simple graph as a Studio graph the user can open on the canvas.

    ``blocks`` are the frozen definitions this pipeline uses, keyed by name; they are
    written into the file so the pipeline stays runnable and portable on its own.
    ``is_block`` marks the file as a block definition, which derives its own interface
    from its boundary wiring and lists under Blocks instead of Pipelines.
    """
    path = graph_path(user, name)
    graph = to_drawflow(nodes, edges, blocks)
    if blocks:
        graph["blocks"] = {n: {"header": b["header"], "body": b["body"]}
                           for n, b in blocks.items()}
    if is_block:
        header = block_ops.derive_interface(nodes, edges, name=path.stem)
        previous = 0
        if path.exists():
            try:
                previous = int((json.loads(path.read_text(encoding="utf-8"))
                                .get("block") or {}).get("version", 0))
            except (ValueError, OSError):
                previous = 0
        header["version"] = previous + 1     # every save is a version a pipeline can pin
        graph["block"] = header
    path.write_text(json.dumps(graph), encoding="utf-8")
    if description:
        set_description(user_template_root(user), path.stem, description)
    return {"ok": True, "name": path.stem, "nodes": len(nodes),
            "kind": "block" if is_block else "pipeline",
            "version": graph.get("block", {}).get("version") if is_block else None,
            "note": f"“{path.stem}” now appears in the Studio's Templates dropdown."}
