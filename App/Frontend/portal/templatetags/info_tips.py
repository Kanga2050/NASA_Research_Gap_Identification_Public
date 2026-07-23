"""Single source of truth for the workspace's "i" help tooltips.

Every help chip in the UI used to carry its own inline `data-tip="..."` prose,
scattered across workspace.html (~18 copies). They now live here, keyed, and
templates render them with `{% info_tip "import" %}` — so the wording lives in
one place and the accessible markup (role + aria-label) is emitted consistently.
"""

from django import template
from django.utils.html import format_html

register = template.Library()

TIPS = {
    "import": "Upload a CSV, an HTML visualization, or a saved pipeline template (.json) from your computer into your account.",
    "public_library": "Files other users have chosen to share. Click Pull to copy one into your own account.",
    "data": "Your uploaded and generated data tables.",
    "templates": "Saved Studio pipelines, and the charts they've generated -- a recipe and its rendered chart live in the same folder, reload and run one again here or in the Studio tab.",
    "papers": "Research papers written in the Synthesize tab, alongside the interactive report you Build from each one.",
    "pdf_collections": "Folders of PDFs you can chunk into a dataset with the Chunk PDFs task. Upload your own, or pull a shared collection from the public library.",
    "queue_task": "Run one data-processing or visualization step on your files, without building a full Studio pipeline.",
    "recent_tasks": "A history of the steps you've run and whether they succeeded, failed, or are still working.",
    "api_keys": "Secret tokens for accessing your data from outside code, e.g. scripts or notebooks. Keep them private.",
    "view_output": "Preview any CSV table or chart you've generated, not just the most recent one.",
    "export": "Download a copy of one of your files to your computer.",
    "studio_blocks": "Drag any of these onto the canvas to add a pipeline step.",
    "active_tasks": "Tasks currently queued or running, queued from either tab — the same list as the Dashboard's Recent tasks, filtered to what's in progress.",
    "studio_templates": "Save your current canvas as a reusable template, or load one you saved earlier.",
    "synth_paper": "Compose a research paper from your own charts and data. Add sections, cite sources, then Build a self-contained interactive report that lands right alongside this paper.",
    "synth_sources": "Add a source once; cite it inline from the selection toolbar. References are numbered and formatted automatically.",
    "assistant": "A chat assistant with tools for all three tabs: it can inspect your data and queue pipeline steps, read and run Studio pipelines, and read, edit and build the paper open in Synthesize.",
}


@register.simple_tag
def info_tip(key):
    """Render the standard "i" help chip for a known tip key (see TIPS).

    Emits the tooltip text as both the CSS `data-tip` and an `aria-label`
    (with `role="note"`), so assistive tech gets the hint without any JS.
    """
    tip = TIPS.get(key)
    if tip is None:
        raise template.TemplateSyntaxError(
            f"Unknown info_tip key {key!r}; add it to TIPS in info_tips.py"
        )
    return format_html(
        '<span class="info-icon" tabindex="0" role="note" data-tip="{0}" aria-label="{0}">i</span>',
        tip,
    )
