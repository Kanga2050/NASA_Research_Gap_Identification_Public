"""Composite blocks -- reusable sub-pipelines the Studio can collapse into one node.

A block is an ordinary Studio graph with a boundary. Two pseudo-nodes mark that
boundary, so declaring a block's interface is just wiring:

    __block_in__   no inputs, one output per block input   -- wire it to the inner
                   ports the block takes from outside
    __block_out__  one input per block output, no outputs  -- wire the inner results
                   the block hands back

Everything else follows from that. The wire types the canvas already enforces give
the block's ports their types for free, and a port exists exactly when someone drew a
wire to the boundary (grouping a selection draws those wires automatically, from the
inner ports nothing else feeds and the results nothing else consumes).

Three things are true of a block at once:

* **It is its own template.** A block lives in ``templates/<name>.json`` like any
  pipeline, flagged with a ``block`` header, so it lists in the Blocks section, opens
  on the canvas, and can be shared exactly the way a pipeline is.
* **It is embedded where it is used.** A pipeline that uses a block carries a frozen
  copy of the definition and the version it was built against, so opening an old
  pipeline runs what it ran when it was written. ``stale_blocks`` reports when the
  library has moved on, and the canvas offers the update.
* **It is notation, not a runtime.** ``expand`` inlines every instance back into plain
  nodes before anything is queued, so the task engine, the registry and the task
  history never learn that blocks exist.
"""
from __future__ import annotations

import json

def _port_type(action: str, port: int, side: str, blocks: dict | None = None) -> dict:
    """The wire kind (and accepted column types) of one inner port, read from the node
    manifest -- so a block's ports are typed by what they actually connect to and the
    canvas type-checks a composite exactly as it checks any node.

    ``action`` may itself be a block instance (``@Name``): a boundary wired straight into
    a nested block (e.g. Theme_Emphasis's inputs feed ten ``@Emphasis_Probe`` instances)
    is typed by recursing into that block's own already-derived header rather than
    falling back to "any" -- the header carries the same {wire, accepts, kind, type}
    shape ``_port_type`` itself produces, since it is how that block derived its ports.
    """
    if is_instance(action):
        block = (blocks or {}).get(instance_block(action))
        if block is None:
            return {"wire": "any", "accepts": []}
        specs = block["header"]["inputs"] if side == "in" else block["header"]["outputs"]
        spec = specs[port] if port < len(specs) else None
        if not spec:
            return {"wire": "any", "accepts": []}
        return {k: v for k, v in spec.items() if k in ("wire", "accepts", "kind", "type")}

    from .graph_manifest import MANIFEST

    entry = MANIFEST.get(action)
    if entry is None:
        return {"wire": "any", "accepts": []}
    if side == "in":
        specs = list(entry["inputs"])
        var = entry.get("variadic")
        if var and var.get("side") != "output":
            while len(specs) <= port:
                specs.append({"wire": var["wire"], "accepts": list(ANY_COLUMN)})
        spec = specs[port] if port < len(specs) else None
        if not spec:
            return {"wire": "any", "accepts": []}
        return {"wire": spec["wire"], "accepts": list(spec.get("accepts") or [])}
    out = entry["output"]
    kind = out.get("kind")
    if kind == "csv":
        return {"wire": "csv", "accepts": [], "kind": "csv"}
    if kind == "column":
        return {"wire": "column", "accepts": [], "kind": "column", "type": out.get("type", "text")}
    return {"wire": "any", "accepts": []}


ANY_COLUMN = ("text", "number", "date", "embedding")

BLOCK_IN = "__block_in__"
BLOCK_OUT = "__block_out__"
INSTANCE_PREFIX = "@"


class BlockError(ValueError):
    """A block could not be defined, instantiated or expanded."""


def is_instance(action: str) -> bool:
    return bool(action) and action.startswith(INSTANCE_PREFIX)


def instance_block(action: str) -> str:
    return action[len(INSTANCE_PREFIX):]


# --------------------------------------------------------------------------- #
# Interface derivation
# --------------------------------------------------------------------------- #
def derive_interface(nodes: list, edges: list, name: str = "", blocks: dict | None = None) -> dict:
    """Read a definition graph's boundary wiring into a block header.

    Ports come out in port order; a port's type is the type of the wire on it, which
    the canvas has already checked, so a block cannot claim a type its insides do not
    produce. ``params`` are the inner parameters the author chose to expose. ``blocks``
    are the already-known definitions of any nested ``@Name`` instances this one's
    boundary wires into, so their types resolve instead of falling back to "any".
    """
    by_id = {str(n["id"]): n for n in nodes}
    entry_node = next((n for n in nodes if n["action"] == BLOCK_IN), None)
    exit_node = next((n for n in nodes if n["action"] == BLOCK_OUT), None)
    if entry_node is None or exit_node is None:
        raise BlockError("A block definition needs both a Block Inputs and a Block Outputs node.")

    meta = entry_node.get("fields") or {}
    labels_in = _labels(meta.get("labels"))
    labels_out = _labels((exit_node.get("fields") or {}).get("labels"))

    # One boundary port may feed SEVERAL inner ports -- an embedding handed to ten
    # probes is one input, ten targets -- so a port carries every target it reaches.
    inputs = []
    by_port = {}
    for edge in sorted(edges, key=lambda e: (int(e.get("fromPort", 0)), str(e.get("to")))):
        if str(edge.get("from")) != str(entry_node["id"]):
            continue
        port = int(edge.get("fromPort", 0))
        target = {"node": str(edge["to"]), "to_port": int(edge.get("toPort", 0)),
                  "action": (by_id.get(str(edge["to"])) or {}).get("action", "")}
        if port in by_port:
            by_port[port]["targets"].append(target)
            continue
        spec = {"port": port, "name": labels_in.get(port) or f"in{port + 1}",
                "targets": [target],
                # the first target, kept flat for readers that only need one
                "node": target["node"], "to_port": target["to_port"],
                "action": target["action"],
                **_port_type(target["action"], target["to_port"], "in", blocks)}
        by_port[port] = spec
        inputs.append(spec)

    outputs = []
    for edge in sorted(edges, key=lambda e: int(e.get("toPort", 0))):
        if str(edge.get("to")) != str(exit_node["id"]):
            continue
        port = int(edge.get("toPort", 0))
        producer = by_id.get(str(edge["from"])) or {}
        outputs.append({"port": port,
                        "name": labels_out.get(port) or f"out{port + 1}",
                        "node": str(edge["from"]),
                        "from_port": int(edge.get("fromPort", 0)),
                        **_port_type(producer.get("action", ""), int(edge.get("fromPort", 0)),
                                    "out", blocks)})

    promoted = meta.get("promoted") or []
    if isinstance(promoted, str):
        promoted = json.loads(promoted or "[]")
    params = []
    for item in promoted:
        node = by_id.get(str(item.get("node")))
        if not node:
            continue
        param = item["param"]
        default = node.get(param, "") if param in ("column", "csv") \
            else (node.get("fields") or {}).get(param, "")
        params.append({"name": item.get("name") or param,
                       "node": str(item["node"]), "param": param, "default": default})

    header = {"name": name or meta.get("block") or "Block",
              "version": int(meta.get("version") or 1),
              "inputs": inputs, "outputs": outputs, "params": params}
    _check_self_reference(header["name"], nodes, blocks)
    _check_types(header, nodes, edges, blocks)
    return header


def _check_self_reference(name: str, nodes: list, blocks: dict | None) -> None:
    """A block cannot use an instance of itself, directly or through a nested block it
    already carries the definition of -- ``expand``'s depth-8 bound catches a cycle at
    run time, but failing here at save time gives a clear error before one is ever
    written to disk."""
    seen = set()

    def contains(name_to_check, body_nodes):
        for node in body_nodes:
            action = node.get("action", "")
            if not is_instance(action):
                continue
            used = instance_block(action)
            if used == name_to_check:
                return True
            if used in seen:
                continue
            seen.add(used)
            nested = (blocks or {}).get(used)
            if nested and contains(name_to_check, nested["body"]["nodes"]):
                return True
        return False

    if contains(name, nodes):
        raise BlockError(f"{name!r} cannot contain an instance of itself.")


def _check_types(header: dict, nodes: list, edges: list, blocks: dict | None = None) -> None:
    """Every wire inside the definition must be type-compatible, and every boundary port
    must carry the type of the inner port it stands for. The canvas checks this live as
    wires are drawn; this re-checks it when a block is saved, so a block cannot be stored
    with a port that lies about what it accepts or emits."""
    by_id = {str(n["id"]): n for n in nodes}

    # Only the wire KIND (csv vs column) is statically known: a Select Column's or an
    # annotation's output column type is chosen at run time, so column subtypes are
    # checked live on the canvas, not here.
    for edge in edges:
        src = by_id.get(str(edge.get("from")))
        dst = by_id.get(str(edge.get("to")))
        if not src or not dst or dst["action"] in (BLOCK_OUT,) or src["action"] in (BLOCK_IN,):
            continue
        pw = _port_type(src["action"], int(edge.get("fromPort", 0)), "out", blocks).get("wire")
        aw = _port_type(dst["action"], int(edge.get("toPort", 0)), "in", blocks).get("wire")
        if pw and aw and "any" not in (pw, aw) and pw != aw:
            raise BlockError(
                f"{src['action']} emits a {pw} wire into {dst['action']}, which wants {aw}.")


def _labels(raw) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except ValueError:
            raw = []
    return {i: v for i, v in enumerate(raw or []) if v}


def definition_body(nodes: list, edges: list) -> dict:
    """The definition minus its boundary nodes -- what an instance actually runs."""
    boundary = {str(n["id"]) for n in nodes if n["action"] in (BLOCK_IN, BLOCK_OUT)}
    return {
        "nodes": [n for n in nodes if str(n["id"]) not in boundary],
        "edges": [e for e in edges
                  if str(e.get("from")) not in boundary and str(e.get("to")) not in boundary],
    }


# --------------------------------------------------------------------------- #
# Expansion (what Run does before anything is queued)
# --------------------------------------------------------------------------- #
def expand(nodes: list, edges: list, blocks: dict, _depth: int = 0) -> tuple[list, list]:
    """Inline every block instance, returning a plain graph of real nodes.

    Definition regions are dropped: they are a picture of what the block does, not a
    step in this pipeline. Each instance is replaced by a private copy of the block's
    inner nodes (ids prefixed so two instances never collide), its promoted parameters
    are written onto the inner nodes they came from, and the wires that reached the
    instance are re-pointed at the inner ports the block's boundary named.
    """
    nodes = [n for n in nodes if not (n.get("fields") or {}).get("__def_of__")
             and n.get("def_of") is None]
    by_id = {str(n["id"]): n for n in nodes}

    out_nodes, out_edges = [], []
    # instance id -> {"in": {port: (node_id, to_port)}, "out": {port: (node_id, from_port)}}
    wiring = {}

    for node in nodes:
        action = node.get("action", "")
        if not is_instance(action):
            out_nodes.append(node)
            continue

        name = instance_block(action)
        block = (blocks or {}).get(name)
        if not block:
            raise BlockError(
                f"Node {node['id']} uses block {name!r}, but this pipeline carries no "
                "definition for it. Re-insert the block, or open its template.")
        header, body = block["header"], block["body"]

        prefix = f"b{node['id']}_"
        # A promoted argument writes onto the inner node it was exposed from. Most land
        # in that node's `fields`; `column`/`csv` are stored at the node's top level
        # (that is where Select Column and CSV Input keep them), so they are applied
        # there instead -- which is how an argument like a Select Column's picked column
        # reaches the outside.
        inner_fields, inner_top = {}, {}
        for param in header["params"]:
            value = (node.get("fields") or {}).get(param["name"])
            if value in (None, ""):
                continue
            if param["param"] in ("column", "csv"):
                inner_top.setdefault(param["node"], {})[param["param"]] = value
            else:
                inner_fields.setdefault(param["node"], {})[param["param"]] = value

        # Tables a block writes internally are made unique per instance, so ten instances
        # of the same block do not all write the same file (and clobber each other under
        # FIFO). The block's declared OUTPUT tables keep their public name -- the enclosing
        # graph reaches them by wire, and their name is what a downstream reads on disk.
        output_ids = {str(o["node"]) for o in header["outputs"]}
        for inner in body["nodes"]:
            copy = dict(inner)
            copy["id"] = prefix + str(inner["id"])
            fields = dict(inner.get("fields") or {})
            fields.update(inner_fields.get(str(inner["id"]), {}))
            if str(inner["id"]) not in output_ids:
                for table_field in ("output_csv", "csv_name"):
                    if fields.get(table_field):
                        fields[table_field] = prefix + str(fields[table_field])
            copy["fields"] = fields
            for key, value in inner_top.get(str(inner["id"]), {}).items():
                copy[key] = value
            out_nodes.append(copy)
        for inner_edge in body["edges"]:
            out_edges.append({"from": prefix + str(inner_edge["from"]),
                              "to": prefix + str(inner_edge["to"]),
                              "toPort": int(inner_edge.get("toPort", 0)),
                              "fromPort": int(inner_edge.get("fromPort", 0))})

        wiring[str(node["id"])] = {
            "in": {p["port"]: [(prefix + str(t["node"]), int(t.get("to_port", 0)))
                               for t in (p.get("targets")
                                         or [{"node": p["node"], "to_port": p.get("to_port", 0)}])]
                   for p in header["inputs"]},
            "out": {p["port"]: (prefix + str(p["node"]), int(p.get("from_port", 0)))
                    for p in header["outputs"]},
        }

    for edge in edges:
        src, dst = str(edge.get("from")), str(edge.get("to"))
        if src not in by_id or dst not in by_id:
            continue                       # an edge into a dropped definition region
        from_port, to_port = int(edge.get("fromPort", 0)), int(edge.get("toPort", 0))
        if src in wiring:
            resolved = wiring[src]["out"].get(from_port)
            if resolved is None:
                raise BlockError(f"Block instance {src} has no output port {from_port}.")
            src, from_port = resolved
        # A wire into a block input reaches every inner port that boundary port feeds.
        targets = [(dst, to_port)]
        if dst in wiring:
            targets = wiring[dst]["in"].get(to_port)
            if targets is None:
                raise BlockError(f"Block instance {dst} has no input port {to_port}.")
        for inner_dst, inner_port in targets:
            out_edges.append({"from": src, "to": inner_dst, "toPort": inner_port,
                              "fromPort": from_port})

    # A block may be built out of other blocks; keep inlining until only real nodes
    # remain (bounded, so a definition that somehow contains itself fails loudly).
    if any(is_instance(n.get("action", "")) for n in out_nodes):
        if _depth >= 8:
            raise BlockError("Block definitions are nested more than 8 deep, or contain a cycle.")
        return expand(out_nodes, out_edges, blocks, _depth + 1)
    return out_nodes, out_edges


# --------------------------------------------------------------------------- #
# Freshness
# --------------------------------------------------------------------------- #
def stale_blocks(embedded: dict, library: dict) -> list[dict]:
    """Blocks a pipeline froze that the library has since moved past."""
    out = []
    for name, block in (embedded or {}).items():
        current = (library or {}).get(name)
        if current and int(current) > int(block["header"].get("version", 1)):
            out.append({"name": name, "used": block["header"].get("version", 1),
                        "available": int(current)})
    return out
