"""Render a Synthesize paper (a block-model JSON document) into a SELF-CONTAINED,
INTERACTIVE HTML file.

This is the server-side authoritative renderer. ``render_fragment(doc)`` turns the
block model into the exact ``<div class="page">…</div>`` markup the editor shows
(so the editing canvas and the built report are identical by construction), and
``build_paper_html(doc, html_root)`` wraps that fragment with the report stylesheet
and swaps every figure placeholder for a live Plotly chart — inlining plotly.js
exactly once (pulled out of an existing chart file so the version always matches),
exactly like the hand-written ``build_interactive.py`` did.

A figure whose referenced HTML is not a Plotly chart (e.g. it is itself a *built
paper*) is embedded via an ``<iframe srcdoc>`` fallback, so a finished report can
be dropped in as a figure of another paper.

The module is intentionally dependency-light (stdlib only) so it can be imported at
Django URL-load time without any app/runtime coupling.
"""
from __future__ import annotations

import html as _html
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_H = 500          # default figure height (px); width is always the column width
PAPER_EMBED_H = 760      # default height for an embedded paper/non-chart HTML

# The report stylesheet, verbatim from the hand-authored template so the built
# paper is visually identical to the original Space Biology report and to the
# Synthesize editor canvas (which reuses these same class names).
PAPER_CSS = """<style>
  :root { --ink:#1a1a1a; --muted:#5b6472; --rule:#d9dde3; --accent:#1c4e80; --danger:#b91c1c;
          --soft:#f5f7fa; --green:#15803d; }
  * { box-sizing:border-box; }
  body { margin:0; background:#ffffff; color:var(--ink);
         font-family: Georgia, Charter, "Times New Roman", serif;
         font-size:17px; line-height:1.66; -webkit-font-smoothing:antialiased; }
  .page { max-width:860px; margin:0 auto; padding:60px 32px 120px; }
  h1,h2,h3,h4,.byline,.abstract-h,figcaption,.tag,thead th,.callout-h { font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
  h1 { font-size:31px; line-height:1.22; letter-spacing:-0.2px; margin:0 0 14px; }
  .subtitle { font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
              font-size:17px; color:var(--muted); font-weight:500; margin:0 0 22px; line-height:1.4; }
  .byline { font-size:13.5px; color:var(--muted); border-top:1px solid var(--rule);
            border-bottom:1px solid var(--rule); padding:12px 0; margin:0 0 24px;
            display:flex; flex-wrap:wrap; gap:6px 22px; }
  .byline b { color:var(--ink); font-weight:600; }
  h2 { font-size:22px; margin:52px 0 6px; padding-top:14px; border-top:2px solid var(--ink); }
  h2 .num { color:var(--accent); margin-right:12px; }
  h3 { font-size:17.5px; margin:30px 0 4px; color:#222; }
  h3 .num { color:var(--accent); margin-right:9px; font-weight:600; }
  p { margin:12px 0; }
  a { color:var(--accent); }
  .lead { font-size:18px; }
  .abstract { background:var(--soft); border:1px solid var(--rule); border-radius:8px;
              padding:22px 26px; margin:6px 0 10px; }
  .abstract-h { font-size:12.5px; letter-spacing:1.4px; text-transform:uppercase;
                color:var(--accent); font-weight:700; margin:0 0 8px; }
  .abstract p { margin:8px 0; font-size:16px; line-height:1.6; }
  .kw { font-size:14px; color:var(--muted); margin:14px 0 0; }
  .kw b { font-family:-apple-system,"Segoe UI",sans-serif; color:var(--ink); }
  figure { margin:30px 0; }
  .fig-img { width:100%; height:auto; display:block; border:1px solid var(--rule);
             border-radius:6px; background:#fff; }
  figcaption { font-size:13.5px; line-height:1.5; color:var(--muted); margin-top:10px;
               padding-left:2px; }
  figcaption b { color:var(--ink); font-weight:600; }
  .figtag { font-family:-apple-system,"Segoe UI",sans-serif; font-size:11px; letter-spacing:0.4px;
            text-transform:uppercase; font-weight:700; color:var(--accent); }
  .zoompair { display:grid; grid-template-columns:1fr 1fr; gap:18px; }
  @media (max-width:680px){ .zoompair{ grid-template-columns:1fr; } .page{padding:40px 18px 90px;} }
  table { border-collapse:collapse; width:100%; margin:22px 0; font-size:14px;
          font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
  thead th { text-align:left; border-bottom:2px solid var(--ink); padding:8px 10px; font-size:13px; }
  td { border-bottom:1px solid var(--rule); padding:7px 10px; vertical-align:top; }
  tbody tr:nth-child(even){ background:#fafbfc; }
  .num-cell { text-align:right; font-variant-numeric:tabular-nums; }
  .pos { color:var(--green); font-weight:600; }
  .neg { color:var(--danger); font-weight:600; }
  .callout { border-left:4px solid var(--accent); background:var(--soft);
             padding:14px 20px; margin:24px 0; border-radius:0 6px 6px 0; }
  .callout.danger { border-left-color:var(--danger); }
  .callout.key { border-left-color:var(--green); }
  .callout-h { font-size:12px; letter-spacing:1.2px; text-transform:uppercase;
               font-weight:700; color:var(--accent); margin:0 0 4px; }
  .callout.danger .callout-h { color:var(--danger); }
  .callout.key .callout-h { color:var(--green); }
  .callout p { margin:4px 0; font-size:15.5px; }
  .footnote { font-size:13px; color:var(--muted); }
  hr.soft { border:0; border-top:1px solid var(--rule); margin:40px 0; }
  .tag { display:inline-block; font-size:11px; letter-spacing:0.6px; text-transform:uppercase;
         background:#eef2f7; color:var(--accent); border-radius:4px; padding:2px 8px; font-weight:600;
         vertical-align:middle; }
  ul.tight li { margin:5px 0; }
  .interactive { display:flex; align-items:center; gap:10px; background:#eef4fb;
                 border:1px solid #cfe0f2; border-radius:8px; padding:10px 16px; margin:0 0 30px;
                 font-family:-apple-system,"Segoe UI",sans-serif; font-size:13.5px; color:#274b6d; }
  .interactive b { color:#1c4e80; }
  .refs { font-size:13px; line-height:1.5; }
  .refs li { margin:6px 0; }
  sup.r { font-size:11px; font-family:-apple-system,sans-serif; }
  sup.r a { text-decoration:none; }
</style>"""

PLOT_CSS = ("<style>"
            ".plot-holder{width:100%;border:1px solid var(--rule,#e5e7eb);border-radius:6px;"
            "background:#fff;padding:6px 4px;margin:0;overflow:hidden;}"
            ".plot-holder .plotly-graph-div{width:100%;}"
            ".paper-embed{width:100%;border:1px solid var(--rule,#e5e7eb);border-radius:6px;"
            "background:#fff;}"
            "@media print{.plot-holder,.paper-embed{break-inside:avoid;}}"
            "</style>")


# --------------------------------------------------------------------------- #
# Inline text: allow only a small, known-safe subset of markup through.
# --------------------------------------------------------------------------- #
_ALLOWED_INLINE_TAGS = {"b", "strong", "i", "em", "sup", "sub", "a", "span"}
_ALLOWED_INLINE_ATTRS = {"a": {"href"}, "span": {"class"}}
_ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}


def _safe_url(value: str) -> str:
    try:
        scheme = urlsplit(value).scheme.lower()
    except ValueError:
        return "#"
    # No scheme at all (relative link / #fragment) is fine; anything with an
    # explicit scheme must be on the allowlist (blocks javascript:, data:, vbscript:…).
    if scheme and scheme not in _ALLOWED_URL_SCHEMES:
        return "#"
    return value


class _InlineSanitizer(HTMLParser):
    """Allowlist-based sanitizer for author-supplied inline HTML: only
    _ALLOWED_INLINE_TAGS survive, only _ALLOWED_INLINE_ATTRS on those tags, and
    only http(s)/mailto URLs. Everything else (script, iframe, object, svg, style,
    event-handler attributes, javascript:/data: URIs, …) is dropped as a tag but
    its inner text is kept (escaped), matching an editor's expectation that typing
    an unsupported tag loses the markup, not the content."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.out: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in _ALLOWED_INLINE_TAGS:
            return
        allowed_attrs = _ALLOWED_INLINE_ATTRS.get(tag, set())
        kept = []
        for name, value in attrs:
            if name not in allowed_attrs:
                continue
            value = value or ""
            if name == "href":
                value = _safe_url(value)
            kept.append(f'{name}="{_html.escape(value, quote=True)}"')
        attr_str = (" " + " ".join(kept)) if kept else ""
        self.out.append(f"<{tag}{attr_str}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in _ALLOWED_INLINE_TAGS:
            self.out.append(f"</{tag}>")

    def handle_endtag(self, tag):
        if tag in _ALLOWED_INLINE_TAGS:
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        self.out.append(_html.escape(data, quote=False))

    def handle_entityref(self, name):
        self.out.append(f"&{name};")

    def handle_charref(self, name):
        self.out.append(f"&#{name};")


def _clean_inline(text) -> str:
    """Sanitize author inline HTML down to _ALLOWED_INLINE_TAGS/_ALLOWED_INLINE_ATTRS.
    Bold, italic, tag pills, citation sups and anchors pass through untouched."""
    if text is None:
        return ""
    parser = _InlineSanitizer()
    parser.feed(str(text))
    parser.close()
    return "".join(parser.out)


def _esc(text) -> str:
    return _html.escape("" if text is None else str(text), quote=True)


def _attr(text) -> str:
    return _html.escape("" if text is None else str(text), quote=True)


# --------------------------------------------------------------------------- #
# Block renderers — each returns the exact report markup for one block.
# --------------------------------------------------------------------------- #
def _render_reference(src: dict, n: int) -> str:
    """Format one source into an <li id="rN">…</li> reference entry."""
    if src.get("text"):                      # fully hand-written entry
        return f'<li id="r{n}">{_clean_inline(src["text"])}</li>'
    parts = []
    authors = (src.get("authors") or "").strip()
    title = (src.get("title") or "").strip()
    journal = (src.get("journal") or "").strip()
    year = (src.get("year") or "").strip()
    url = (src.get("url") or "").strip()
    doi = (src.get("doi") or "").strip()
    if authors:
        parts.append(_esc(authors) + ",")
    if title:
        parts.append(f'&ldquo;{_esc(title)}&rdquo;,')
    if journal:
        parts.append(f'<i>{_esc(journal)}</i>')
    if year:
        parts.append(_esc(year) + ("," if url else "."))
    if url:
        link = f"doi:{_esc(doi)}" if doi else _esc(url)
        parts.append(f'<a href="{_attr(url)}">{link}</a>.')
    return f'<li id="r{n}">{" ".join(parts).strip()}</li>'


def _render_table(block: dict) -> str:
    head = block.get("head") or []
    rows = block.get("rows") or []
    out = ["<table>"]
    if head:
        out.append("<thead><tr>"
                   + "".join(f"<th>{_clean_inline(h)}</th>" for h in head)
                   + "</tr></thead>")
    out.append("<tbody>")
    for row in rows:
        cells = []
        for cell in row:
            if isinstance(cell, dict):
                cls = cell.get("cls", "")
                clsattr = f' class="{_attr(cls)}"' if cls else ""
                cells.append(f"<td{clsattr}>{_clean_inline(cell.get('html', ''))}</td>")
            else:
                cells.append(f"<td>{_clean_inline(cell)}</td>")
        out.append("<tr>" + "".join(cells) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def assign_numbers(doc: dict) -> dict:
    """Auto-number the document's headings, in place.

    Headings count 1, 2, 3…; each sub-heading is numbered within its parent
    heading (2.1, 2.2, …) and the sub-counter resets at every new heading. A block
    with ``"unnumbered": true`` is skipped and takes no number (and, for a heading,
    does not advance the counter). Sub-headings before the first heading are left
    unnumbered. The stored ``num`` is always overwritten, so the numbering can never
    drift from the document order — insert or delete a section and everything after
    it renumbers itself. The editor (synthesize.js ``assignNumbers``) applies the
    identical rule, so the canvas and the built report always agree.
    """
    heading_n = 0
    sub_n = 0
    for block in (doc.get("blocks") or []):
        kind = block.get("type")
        if kind == "heading":
            if block.get("unnumbered"):
                block["num"] = ""
                continue
            heading_n += 1
            sub_n = 0
            block["num"] = str(heading_n)
        elif kind == "subheading":
            if block.get("unnumbered") or heading_n == 0:
                block["num"] = ""
                continue
            sub_n += 1
            block["num"] = f"{heading_n}.{sub_n}"
    return doc


def render_fragment(doc: dict) -> str:
    """Render the whole document to the ``<div class="page">…</div>`` fragment.
    Figures are emitted as ``<img class="fig-img" data-shot="NAME">`` placeholders
    that ``build_paper_html`` later swaps for live charts. Figures are auto-numbered,
    headings/sub-headings are numbered by ``assign_numbers``, and the References
    block is auto-generated from ``doc['sources']``."""
    assign_numbers(doc)
    blocks = doc.get("blocks") or []
    sources = doc.get("sources") or []
    out = ["<div class=\"page\">"]

    title = (doc.get("title") or "").strip()
    if title:
        out.append(f"<h1>{_clean_inline(title)}</h1>")

    fig_n = 0
    for block in blocks:
        t = block.get("type")
        if t == "subtitle":
            out.append(f'<div class="subtitle">{_clean_inline(block.get("html"))}</div>')
        elif t == "byline":
            spans = "".join(
                f'<span><b>{_esc(it.get("label"))}:</b> {_clean_inline(it.get("value"))}</span>'
                for it in (block.get("items") or [])
            )
            out.append(f'<div class="byline">{spans}</div>')
        elif t == "interactive":
            out.append('<div class="interactive"><span style="font-size:18px">&#10035;</span>'
                       f'<span>{_clean_inline(block.get("html"))}</span></div>')
        elif t == "abstract":
            paras = "".join(f"<p>{_clean_inline(p)}</p>" for p in (block.get("paras") or []))
            out.append(f'<div class="abstract"><div class="abstract-h">Abstract</div>{paras}</div>')
        elif t == "keywords":
            out.append(f'<p class="kw"><b>Keywords:</b> {_clean_inline(block.get("html"))}</p>')
        elif t == "heading":
            num = block.get("num", "")
            numspan = f'<span class="num">{_esc(num)}</span>' if num else ""
            out.append(f"<h2>{numspan}{_clean_inline(block.get('text'))}</h2>")
        elif t == "subheading":
            num = block.get("num", "")
            numspan = f'<span class="num">{_esc(num)}</span>' if num else ""
            tag = block.get("tag", "")
            tagspan = f' <span class="tag">{_esc(tag)}</span>' if tag else ""
            out.append(f"<h3>{numspan}{_clean_inline(block.get('text'))}{tagspan}</h3>")
        elif t == "paragraph":
            cls = ' class="lead"' if block.get("variant") == "lead" else ""
            out.append(f"<p{cls}>{_clean_inline(block.get('html'))}</p>")
        elif t == "figure":
            fig_n += 1
            chart = _attr(block.get("chart", ""))
            alt = _attr(block.get("alt", ""))
            tagbits = f"Figure&nbsp;{fig_n} &middot; interactive"
            if block.get("new"):
                tagbits += " &middot; new"
            headline = block.get("headline", "")
            head_html = f"<b>{_clean_inline(headline)}</b> " if headline else ""
            out.append(
                f'<figure><img class="fig-img" data-shot="{chart}" alt="{alt}">'
                f'<figcaption><span class="figtag">{tagbits}</span> '
                f'{head_html}{_clean_inline(block.get("caption"))}</figcaption></figure>'
            )
        elif t == "callout":
            variant = block.get("variant", "")
            vcls = f" {variant}" if variant in ("key", "danger") else ""
            body_parts = []
            if block.get("paras"):
                body_parts = [f"<p>{_clean_inline(p)}</p>" for p in block["paras"]]
            elif block.get("html"):
                body_parts = [f"<p>{_clean_inline(block['html'])}</p>"]
            out.append(f'<div class="callout{vcls}"><div class="callout-h">'
                       f'{_esc(block.get("title"))}</div>{"".join(body_parts)}</div>')
        elif t == "table":
            out.append(_render_table(block))
        elif t == "list":
            items = "".join(f"<li>{_clean_inline(i)}</li>" for i in (block.get("items") or []))
            out.append(f'<ul class="tight">{items}</ul>')
        elif t == "divider":
            out.append('<hr class="soft">')
        elif t == "references":
            entries = "".join(_render_reference(s, i + 1) for i, s in enumerate(sources))
            out.append(f'<h3>References</h3><ol class="refs">{entries}</ol>')
        elif t == "footnote":
            out.append(f'<p class="footnote">{_clean_inline(block.get("html"))}</p>')
        # unknown block types are skipped silently

    out.append("</div>")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Chart embedding — inline plotly.js once, swap each figure placeholder.
# --------------------------------------------------------------------------- #
_LIB_RE = re.compile(r'(<script>/\*\*\s*\n\* plotly\.js.*?</script>)', re.S)


def _roots(html_root) -> list[Path]:
    """Normalise a single root or a list of roots -- a figure may name a plain
    chart (living with its Studio recipe) or another paper's built report (living
    with that paper's document), so both roots are searched in order."""
    return [Path(r) for r in ([html_root] if isinstance(html_root, (str, Path)) else html_root)]


def _find_chart(html_root, name: str):
    """Locate NAME.html anywhere under html_root -- charts live in real subfolders
    now (Figures/, Extras/, ...), so a direct root/name join would miss them."""
    for root in _roots(html_root):
        if not root.is_dir():
            continue
        direct = root / f"{name}.html"
        if direct.is_file():
            return direct
        for found in sorted(root.rglob(f"{name}.html")):
            return found
    return None


def _extract_lib(html_root):
    """Pull the inline plotly.js <script> out of any chart file in html_root
    (they all bundle the same version). Returns the script string, or None."""
    for root in _roots(html_root):
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.html")):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            m = _LIB_RE.search(text)
            if m:
                return m.group(1)
    return None


def _plotly_fragment(name: str, html_root, height: int):
    """If NAME.html is a Plotly chart, return (holder_html, True): its graph div +
    the real newPlot script + a responsive resize IIFE. Otherwise return (None, False)."""
    path = _find_chart(html_root, name)
    if path is None:
        return None, False
    with open(path, encoding="utf-8") as f:
        h = f.read()
    m = re.search(r'<div id="([0-9a-fA-F-]+)" class="plotly-graph-div"', h)
    if not m:
        return None, False       # not a plotly chart (e.g. a built paper) -> caller falls back
    did = m.group(1)
    divm = re.search(r'(<div id="%s" class="plotly-graph-div"[^>]*></div>)' % re.escape(did), h)
    graph_div = divm.group(1) if divm else f'<div id="{did}" class="plotly-graph-div"></div>'
    idx = h.rfind('Plotly.newPlot(')        # the real call (the library ref is earlier)
    if idx == -1:
        return None, False
    start = h.rfind('<script', 0, idx)
    end = h.index('</script>', idx) + len('</script>')
    script = h[start:end]
    graph_div = re.sub(r'style="[^"]*"', f'style="width:100%;height:{height}px;"', graph_div)
    if 'style=' not in graph_div:
        graph_div = graph_div.replace('></div>', f' style="width:100%;height:{height}px;"></div>')
    resize = (f'<script>(function(){{var gd=document.getElementById("{did}");'
              f'function fit(){{if(gd&&window.Plotly){{try{{Plotly.relayout(gd,'
              f'{{width:gd.parentElement.clientWidth,height:{height}}});}}catch(e){{}}}}}}'
              f'if(document.readyState!=="loading")setTimeout(fit,0);'
              f'else document.addEventListener("DOMContentLoaded",fit);'
              f'window.addEventListener("resize",fit);}})();</script>')
    return f'<div class="plot-holder">{graph_div}\n{script}\n{resize}</div>', True


def _iframe_fragment(name: str, html_root, height: int):
    """Embed a non-chart HTML file (e.g. a built paper) via a self-contained
    <iframe srcdoc> so it still works offline. Returns None if the file is missing."""
    path = _find_chart(html_root, name)
    if path is None:
        return None
    with open(path, encoding="utf-8") as f:
        content = f.read()
    srcdoc = _html.escape(content, quote=True)
    return (f'<iframe class="paper-embed" style="height:{max(height, PAPER_EMBED_H)}px" '
            f'srcdoc="{srcdoc}"></iframe>')


def _missing_holder(name: str, height: int) -> str:
    return (f'<div class="plot-holder" style="height:{height}px;display:flex;align-items:center;'
            f'justify-content:center;color:#b91c1c;background:#fef2f2">[missing chart: {_esc(name)}]</div>')


def build_paper_html(doc: dict, html_root) -> str:
    """Render ``doc`` to a self-contained, interactive HTML string: the report
    fragment + stylesheet, with each figure placeholder replaced by a live chart
    (or an iframe fallback), and plotly.js inlined exactly once when needed."""
    fragment = render_fragment(doc)

    # Per-figure heights, keyed by chart name, taken from the figure blocks.
    heights = {}
    for block in (doc.get("blocks") or []):
        if block.get("type") == "figure" and block.get("chart"):
            try:
                heights[block["chart"]] = int(block.get("height") or DEFAULT_H)
            except (TypeError, ValueError):
                heights[block["chart"]] = DEFAULT_H

    lib = _extract_lib(html_root)
    used_lib = {"flag": False}

    def repl(match):
        name = match.group(1)
        height = heights.get(name, DEFAULT_H)
        holder, is_plotly = _plotly_fragment(name, html_root, height)
        if is_plotly:
            used_lib["flag"] = True
            return holder
        frag = _iframe_fragment(name, html_root, height)
        if frag is not None:
            return frag
        return _missing_holder(name, height)

    body = re.sub(r'<img class="fig-img" data-shot="([^"]+)"[^>]*>', repl, fragment)

    title = (doc.get("title") or "Research paper").strip()
    lib_script = (lib + "\n") if (lib and used_lib["flag"]) else ""
    config_script = ("<script>window.PlotlyConfig = {MathJaxConfig: 'local'};</script>\n"
                     if used_lib["flag"] else "")

    head = ("<!doctype html>\n<html lang=\"en\">\n<head>\n"
            "<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<meta name=\"color-scheme\" content=\"light\">\n"
            f"<title>{_esc(title)}</title>\n"
            + PAPER_CSS + "\n" + PLOT_CSS + "\n"
            + config_script + lib_script
            + "</head>\n<body>\n")
    return head + body + "\n</body>\n</html>\n"
