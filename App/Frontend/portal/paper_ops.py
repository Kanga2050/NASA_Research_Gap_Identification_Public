"""Paper (Synthesize) operations, shared by the Django views, the REST API and MCP.

A *paper* is a block-model JSON document stored under ``<user>/papers/<name>.json``.
Everything that can happen to one -- list, read, outline, write, patch, build --
lives here so the browser editor and the AI agent drive the exact same code paths
and can never disagree about the document model.

The block model is documented once, in ``PAPER_SCHEMA_DOC``: that string is what
the ``get_paper_schema`` API/MCP tool returns, so an agent can teach itself the
format before editing a paper.
"""
from __future__ import annotations

import json
import re

from .file_meta import DESCRIPTIONS_FILE, get_description, set_description
from .output_preview import resolve_safe_path
from App.Frontend.webapp.storage import user_html_root, user_paper_root
from App.Servers.Paper_Builder import assign_numbers, build_paper_html
from App.Servers.storage_paths import resolve_html_path


PAPER_SCHEMA_DOC = """\
A Synthesize paper is a JSON document:

  {"title": str, "blocks": [ ...block... ], "sources": [ ...source... ]}

`blocks` is the paper's content, in reading order. Every block is an object with a
`type` and the fields for that type:

  {"type":"subtitle",   "html": str}                      the deck under the title
  {"type":"byline",     "items":[{"label":str,"value":str}, ...]}
  {"type":"abstract",   "paras":[str, ...]}
  {"type":"keywords",   "html": str}                      "kw · kw · kw"
  {"type":"interactive","html": str}                      the blue "every figure is live" banner
  {"type":"heading",    "text": str}                      a numbered section (<h2>)
  {"type":"subheading", "text": str, "tag": str}          a numbered subsection (<h3>); `tag`
                                                          is an optional small pill, e.g. "new capability"
  {"type":"paragraph",  "html": str, "variant":"lead"|""} body text; "lead" is the larger opener
  {"type":"figure",     "chart": str, "headline": str, "caption": str,
                        "height": int, "alt": str, "new": bool}
                        `chart` is the NAME (no .html) of one of the user's visualizations --
                        see list_html_files. On build it becomes a LIVE interactive chart.
                        A built paper can itself be used as a `chart` (it embeds as an iframe).
  {"type":"callout",    "variant":""|"key"|"danger", "title": str, "paras":[str, ...]}
                        the boxed asides ("Why this matters methodologically"). "key" is green,
                        "danger" is red, "" is blue. Body text goes in `paras`, one string per
                        paragraph. (A legacy single-paragraph `html` field is still honoured.)
  {"type":"table",      "head":[str, ...], "rows":[[cell, ...], ...]}
                        a cell is a string, or {"html":str,"cls":"num-cell"|"pos"|"neg"}
  {"type":"list",       "items":[str, ...]}
  {"type":"divider"}
  {"type":"references"} renders the numbered reference list from `sources` -- do not write the
                        entries yourself, just place this block (usually near the end)
  {"type":"footnote",   "html": str}

HEADING NUMBERS ARE AUTOMATIC. Never write a `num` field: heading numbers (1, 2, 3…)
and subheading numbers (2.1, 2.2…) are assigned from document order every time the
paper is rendered, so inserting a section renumbers everything after it. Set
`"unnumbered": true` on a heading/subheading to opt one out.

Inline rich text (the `html`/`paras`/`caption`/`items` fields) may contain ONLY:
  <b>bold</b>  <i>italic</i>  <a href="…">link</a>
  <span class="tag">TERM</span>                       a small pill, e.g. a function or column name
  <sup class="r"><a href="#r3">3</a></sup>            a citation of source #3 (1-based index into
                                                      `sources`); the References block numbers itself
                                                      to match, so cite by position.
Anything else (scripts, event handlers) is stripped on render.

`sources` entries are either a raw citation:
  {"text": "Author et al., \\"Title\\", <i>Journal</i>, 2019. <a href=\\"…\\">doi:…</a>"}
or structured fields, auto-formatted for you:
  {"authors": str, "title": str, "journal": str, "year": str, "url": str, "doi": str}
If `text` is set it wins verbatim; otherwise the fields are composed into a citation.
"""


class PaperError(ValueError):
    """A paper could not be read, written, patched or built."""


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #
def safe_name(raw: str) -> str:
    """Reduce a caller-supplied name to a filesystem-safe stem (or "" if unusable)."""
    from pathlib import Path

    safe = re.sub(r"[^\w.\-]", "_", (raw or "").strip()).strip("._ ")
    return "" if safe == Path(DESCRIPTIONS_FILE).stem else safe


def paper_path(user, name: str):
    stem = safe_name(name)
    path = resolve_safe_path(user_paper_root(user), stem, ".json") if stem else None
    if path is None:
        raise PaperError(f"Invalid paper name: {name!r}")
    return path


def list_papers(user) -> list[dict]:
    """Every saved paper: name, description, title and block/source counts."""
    root = user_paper_root(user)
    out = []
    for path in sorted(root.glob("*.json")):
        if path.stem.startswith("_descriptions"):
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        out.append({
            "name": path.stem,
            "title": doc.get("title", ""),
            "description": get_description(root, path.stem),
            "blocks": len(doc.get("blocks") or []),
            "sources": len(doc.get("sources") or []),
        })
    return out


def read_paper(user, name: str) -> dict:
    """The full block-model document, with heading numbers filled in."""
    path = paper_path(user, name)
    if not path.exists():
        raise PaperError(f"No paper named {name!r}. Call list_papers to see what exists.")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise PaperError(f"Paper {name!r} is corrupt: {exc}") from exc
    return assign_numbers(doc)


def _preview(block: dict, limit: int = 90) -> str:
    """One line describing a block's content, for the outline."""
    for key in ("text", "html", "caption", "title"):
        if block.get(key):
            text = str(block[key])
            break
    else:
        if block.get("paras"):
            text = str(block["paras"][0])
        elif block.get("items"):
            first = block["items"][0]
            text = first.get("label", "") if isinstance(first, dict) else str(first)
        elif block.get("head"):
            text = " | ".join(str(h) for h in block["head"])
        else:
            text = ""
    text = " ".join(text.split())
    return text[:limit] + ("…" if len(text) > limit else "")


def outline_paper(user, name: str) -> dict:
    """A compact map of the paper: one line per block, with its INDEX.

    This is the cheap way to see a paper's structure without pulling every word of
    it. The indexes it returns are the ones ``edit_paper`` ops address.
    """
    doc = read_paper(user, name)
    blocks = []
    for i, block in enumerate(doc.get("blocks") or []):
        entry = {"index": i, "type": block.get("type", "")}
        if block.get("num"):
            entry["num"] = block["num"]
        if block.get("type") == "figure":
            entry["chart"] = block.get("chart", "")
        preview = _preview(block)
        if preview:
            entry["preview"] = preview
        blocks.append(entry)
    return {
        "name": name,
        "title": doc.get("title", ""),
        "blocks": blocks,
        "sources": [
            {"index": i + 1, "cite_as": f'<sup class="r"><a href="#r{i + 1}">{i + 1}</a></sup>',
             "citation": s.get("text") or s.get("title") or s.get("authors") or ""}
            for i, s in enumerate(doc.get("sources") or [])
        ],
    }


# --------------------------------------------------------------------------- #
# Write
# --------------------------------------------------------------------------- #
def _validate(doc) -> dict:
    if not isinstance(doc, dict):
        raise PaperError("A paper must be a JSON object with `title`, `blocks` and `sources`.")
    if not isinstance(doc.get("blocks"), list):
        raise PaperError("`blocks` must be a list. Call get_paper_schema for the format.")
    for i, block in enumerate(doc["blocks"]):
        if not isinstance(block, dict) or not block.get("type"):
            raise PaperError(f"Block {i} is not an object with a `type`.")
    doc.setdefault("title", "Untitled paper")
    doc.setdefault("sources", [])
    if not isinstance(doc["sources"], list):
        raise PaperError("`sources` must be a list.")
    return doc


def write_paper(user, name: str, doc: dict, description: str = "") -> dict:
    """Create or overwrite a paper. Returns {name, blocks, sources}."""
    doc = _validate(doc)
    assign_numbers(doc)
    root = user_paper_root(user)
    path = paper_path(user, name)
    path.write_text(json.dumps(doc), encoding="utf-8")
    if description:
        set_description(root, path.stem, description)
    return {"ok": True, "name": path.stem,
            "blocks": len(doc["blocks"]), "sources": len(doc["sources"])}


def edit_paper(user, name: str, ops: list) -> dict:
    """Apply a list of edit operations to a saved paper and save it back.

    Each op is an object with an ``op`` key:

      {"op":"insert",  "index": int, "block": {...}}   insert BEFORE that index
                                                       (index = block count appends)
      {"op":"replace", "index": int, "block": {...}}   swap a block out wholesale
      {"op":"update",  "index": int, "fields": {...}}  merge fields into a block
      {"op":"delete",  "index": int}
      {"op":"move",    "index": int, "to": int}
      {"op":"set_title",   "title": str}
      {"op":"set_sources", "sources": [ ... ]}         replaces the whole list
      {"op":"add_source",  "source": {...}}            appends; returns its cite number

    Ops are applied in order, and indexes refer to the document AS IT IS AT THAT
    MOMENT -- so when inserting several blocks, either go back-to-front or account
    for the shift. Returns the resulting outline so you can check the result.
    """
    doc = read_paper(user, name)
    blocks = doc.setdefault("blocks", [])
    doc.setdefault("sources", [])

    for n, raw in enumerate(ops or []):
        if not isinstance(raw, dict):
            raise PaperError(f"Op {n} is not an object.")
        kind = raw.get("op")

        if kind in ("insert", "replace", "update", "delete", "move"):
            index = raw.get("index")
            if not isinstance(index, int):
                raise PaperError(f"Op {n} ({kind}) needs an integer `index`.")
            limit = len(blocks) if kind == "insert" else len(blocks) - 1
            if index < 0 or index > limit:
                raise PaperError(
                    f"Op {n} ({kind}): index {index} is out of range "
                    f"(the paper has {len(blocks)} blocks)."
                )

        if kind == "insert":
            block = raw.get("block")
            if not isinstance(block, dict) or not block.get("type"):
                raise PaperError(f"Op {n} (insert) needs a `block` object with a `type`.")
            blocks.insert(index, block)
        elif kind == "replace":
            block = raw.get("block")
            if not isinstance(block, dict) or not block.get("type"):
                raise PaperError(f"Op {n} (replace) needs a `block` object with a `type`.")
            blocks[index] = block
        elif kind == "update":
            fields = raw.get("fields")
            if not isinstance(fields, dict):
                raise PaperError(f"Op {n} (update) needs a `fields` object.")
            blocks[index].update(fields)
        elif kind == "delete":
            blocks.pop(index)
        elif kind == "move":
            to = raw.get("to")
            if not isinstance(to, int) or to < 0 or to >= len(blocks):
                raise PaperError(f"Op {n} (move): `to` must be a valid block index.")
            blocks.insert(to, blocks.pop(index))
        elif kind == "set_title":
            doc["title"] = str(raw.get("title", ""))
        elif kind == "set_sources":
            sources = raw.get("sources")
            if not isinstance(sources, list):
                raise PaperError(f"Op {n} (set_sources) needs a `sources` list.")
            doc["sources"] = sources
        elif kind == "add_source":
            source = raw.get("source")
            if not isinstance(source, dict):
                raise PaperError(f"Op {n} (add_source) needs a `source` object.")
            doc["sources"].append(source)
        else:
            raise PaperError(
                f"Op {n}: unknown op {kind!r}. Use insert/replace/update/delete/move/"
                "set_title/set_sources/add_source."
            )

    write_paper(user, name, doc)
    return outline_paper(user, name)


def build_paper(user, name: str, output_name: str = "", description: str = "") -> dict:
    """Render a saved paper into a self-contained interactive HTML report and write
    it into the user's visualizations, where it can be viewed, published, downloaded
    -- or used as a figure inside another paper."""
    doc = read_paper(user, name)
    html_root = user_html_root(user)
    output = safe_name(output_name or name)
    if not output:
        raise PaperError(f"Invalid report name: {output_name!r}")
    out_path = resolve_html_path(output, str(html_root))
    try:
        html = build_paper_html(doc, str(html_root))
    except Exception as exc:  # a bad doc shouldn't 500 the caller
        raise PaperError(f"Build failed: {exc}") from exc
    out_path.write_text(html, encoding="utf-8")
    set_description(html_root, out_path.stem, description or f"Built from paper “{name}”.")
    charts = [b.get("chart") for b in doc.get("blocks", [])
              if b.get("type") == "figure" and b.get("chart")]
    return {"ok": True, "name": out_path.stem, "figures": len(charts),
            "note": f"“{out_path.stem}” is now in the user's visualizations (list_html_files)."}
