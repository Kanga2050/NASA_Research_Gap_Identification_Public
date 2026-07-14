"""The single source of truth for every pipeline function on the platform.

A pipeline function used to be declared in seven places -- its implementation, the
task engine's dotted-path map, the Django form's action list, the view's positional
argument spec, the output-preview's arg-index table, the REST API's request model +
endpoint, and the MCP tool. Adding one meant editing all seven, and nothing checked
that they agreed; a mismatched argument order silently mis-queued a task.

Now each function is declared **once**, here, and every one of those surfaces is
derived from this table:

    task_engine   CALLABLE_PATHS       <- Function.impl
    views         positional task args <- Function.params (in order) + .form_field
    output_preview where the output is <- Function.output_param (no more magic index)
    forms         the action dropdown  <- Function.name / .label
    api_runtime   request model + route<- Function.params + .api_name
    mcp_runtime   tool signature       <- Function.params + .api_name
    graph_manifest Studio node params  <- validated against .form_field at import

The ordering of ``params`` IS the backend function's positional signature -- that is
the contract every caller shares, so it is stated once and never restated.

Three vocabularies, reconciled
------------------------------
The same argument is historically called different things by different surfaces, and
those names are public (the REST API and the MCP tools are used by external clients),
so they are preserved rather than unified:

    Param.name        the backend function's parameter  (authoritative, positional)
    Param.form_field  the Django form / Studio node field
    Param.api_name    the REST body field / MCP tool argument

e.g. ``cluster``'s first coordinate argument is ``embedding_column`` to the backend
and the Studio, but ``coordinate_column`` over the API.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# A param the dashboard form does not expose: it is still passed positionally to the
# backend (so the signature stays aligned), but always at its default. Used where the
# form has no widget for an argument the API does expose -- e.g. label_topics' `top_n`,
# which must NOT pick up the form's chart-oriented `top_n` field (default 25).
NO_FORM = object()

CATEGORIES = ("import", "annotation", "distillation", "visualization")


@dataclass(frozen=True)
class Param:
    """One argument of a pipeline function, in backend positional order."""

    name: str                       # the backend function's parameter name
    type: type = str                # str | int | float | bool (the API/MCP type)
    default: Any = ""               # literal, or callable(cleaned_form) -> value
    doc: str = ""                   # shown in the API docs / MCP tool schema
    form: Any = None                # form field name; None = same as `name`; NO_FORM = hidden
    api: str | None = None          # REST/MCP name; None = same as `name`
    # The MCP tool argument name, on the one param where the two published surfaces
    # never agreed: numerical_filter takes `source_csv` over MCP but `csv_name` over
    # REST. Both are in use, so both are kept; None means MCP uses `api_name` like
    # everything else.
    mcp: str | None = None
    required: bool = False          # required in the API body / MCP call
    # A REST/MCP default, for the few params whose `default` is a callable. A callable
    # default is computed from a sibling FORM field, which an API caller never submits,
    # so those params need a plain value to fall back on over the wire.
    api_default_value: Any = None

    @property
    def form_field(self) -> str | None:
        """The Django-form / Studio-node field feeding this param, or None if hidden."""
        if self.form is NO_FORM:
            return None
        return self.form or self.name

    @property
    def api_name(self) -> str:
        return self.api or self.name

    @property
    def mcp_name(self) -> str:
        return self.mcp or self.api_name

    def api_default(self) -> Any:
        """The default an API/MCP caller gets when they omit this argument."""
        if callable(self.default):
            return self.api_default_value
        return self.default

    def __post_init__(self):
        if callable(self.default) and not self.required and self.api_default_value is None:
            raise ValueError(
                f"Param {self.name!r} has a callable (form-computed) default, so it also "
                "needs an `api_default_value` -- otherwise an API caller who omits it "
                "would send None."
            )


@dataclass(frozen=True)
class Function:
    """One pipeline function, and everything every surface needs to know about it."""

    name: str
    category: str                   # one of CATEGORIES
    impl: str                       # "module.path:attribute" (imported lazily, on run)
    label: str                      # human name, for the dashboard's action dropdown
    summary: str                    # one line, for the API endpoint summary
    description: str                # the prose the API docs AND the MCP tool show
    params: tuple[Param, ...]       # IN BACKEND POSITIONAL ORDER
    roots: tuple[str, ...] = ("csv",)   # storage roots passed as <name>_root kwargs
    # The REST path segment, when it is not just the kebab-cased name. Two endpoints
    # were published under other names before this registry existed and are public, so
    # they keep them rather than breaking existing callers.
    api_path: str | None = None

    @property
    def route(self) -> str:
        return self.api_path or self.name.replace("_", "-")

    @property
    def output_param(self) -> Param:
        """The param naming this function's output file.

        Uniform per category, so it is derived rather than restated: an annotation
        edits its source CSV in place, an import writes a brand-new CSV, a
        distillation writes a derived CSV, and a visualization writes an HTML chart.
        """
        wanted = {
            "annotation": "csv_name",
            "import": "csv_name",
            "distillation": "output_csv",
            "visualization": "output_name",
        }[self.category]
        return self.param(wanted)

    @property
    def output_kind(self) -> str:
        return "html" if self.category == "visualization" else "csv"

    @property
    def output_index(self) -> int:
        """Position of the output param in the queued task's positional args -- how
        the dashboard finds the file a finished task produced."""
        return self.params.index(self.output_param)

    def param(self, name: str) -> Param:
        for p in self.params:
            if p.name == name:
                return p
        raise KeyError(f"{self.name} has no param {name!r}")

    @property
    def form_fields(self) -> tuple[str, ...]:
        return tuple(p.form_field for p in self.params if p.form_field)

    @property
    def source_csv_field(self) -> str | None:
        """The form field that picks an EXISTING CSV to read, or None if this function
        reads no single existing table -- which is how the dashboard decides whether to
        show a CSV dropdown, a free-text "new CSV name" box, or a multi-select.

        An import writes `csv_name` rather than reading it, and combine_csvs takes a
        list (`source_csvs`), so both have no single source to pick.
        """
        if self.category == "import":
            return None
        for field in ("source_csv", "csv_name"):
            if field in self.form_fields:
                return field
        return None


def _p(name, type=str, default="", doc="", form=None, api=None, required=False, api_default=None, mcp=None):
    return Param(name=name, type=type, default=default, doc=doc, form=form, api=api,
                 mcp=mcp, required=required, api_default_value=api_default)


# Params that recur verbatim across many functions.
CSV_NAME = _p("csv_name", str, "", "The CSV dataset to read (no .csv extension).", required=True)
SOURCE_CSV = _p("source_csv", str, "", "The CSV dataset to read (no .csv extension).", required=True)
TEXT_COLUMN = _p("text_column", str, "text", "The column holding the text.")
TOPIC_COLUMN = _p("topic_column", str, "topic_id", "The column holding each row's topic id.")
CHART_TITLE = _p("title", str, "", "Chart title (a sensible one is derived if blank).", form="chart_title")
EXCLUDE = _p("exclude", str, "", "Comma-separated category values to drop first (e.g. \"-1\" for HDBSCAN noise).")


def _out_csv(default, doc="The new CSV to write (no .csv extension)."):
    return _p("output_csv", str, default, doc)


def _out_html(form_stem, api_default):
    """A visualization's output name.

    The two surfaces default it differently, and both are load-bearing: in the
    dashboard the user has already picked a CSV, so the chart is named after it
    ("Space_Biology_bar_chart"); an API caller has submitted no such sibling field, so
    they fall back to a plain static stem -- which is what these endpoints have always
    returned.
    """
    return _p("output_name", str, lambda c: f"{c['csv_name']}_{form_stem}",
              "Name for the rendered HTML chart (no .html extension).",
              api_default=api_default)


# --------------------------------------------------------------------------- #
# Import -- fetch raw data into a brand-new CSV
# --------------------------------------------------------------------------- #
IMPORT_FUNCTIONS = [
    Function(
        name="openalex_scraper",
        category="import",
        impl="App.Backend.importers:openalex_scraper",
        label="OpenAlex scrape",
        summary="Scrape scholarly works for a topic from OpenAlex",
        description=(
            "[Import] Download up to `limit` scholarly works matching `topic` (that have "
            "an abstract) from the OpenAlex API into a brand-new `csv_name` CSV, with "
            "title, abstract, authors, journal, DOI and publish date. The usual starting "
            "point of a pipeline. Queues a background task and returns its task_id."
        ),
        params=(
            _p("topic", str, "space biology", "The search topic.", required=True),
            _p("csv_name", str, "scraped", "The new CSV to write (no .csv extension)."),
            _p("limit", int, 10000, "Maximum number of works to download."),
        ),
        api_path="fetch-data",   # published under this name before it was renamed
    ),
    Function(
        name="chunk_pdfs",
        category="import",
        impl="App.Backend.importers:chunk_pdfs",
        label="Chunk PDFs",
        summary="Chunk one or more PDF collections into a new corpus CSV",
        description=(
            "[Import] Extract text from every PDF in the named `folders` (comma-separated "
            "collection names from your own PDF area or the public library -- call "
            "list_pdf_folders to see them), split it into sentence-aware chunks (~`chunk_words` "
            "words, ~`overlap_words` overlap, never cutting a sentence), and write one row per "
            "chunk to a brand-new `csv_name` CSV with a `text` column plus provenance "
            "(source_file, source, doi, title, authors, journal, publish_time). `source_label` "
            "tags each row's origin (defaults to the collection name). With `enrich`, OSDR-style "
            "DOI filenames are looked up on Crossref for clean authors/journal/title. Feed the "
            "`text` column through embed_text -> reduce_dimensionality -> cluster -> label_topics "
            "to match Space_Biology's columns. Queues a background task and returns its task_id."
        ),
        params=(
            _p("folders", str, "", "Comma-separated PDF collection names.", required=True),
            _p("csv_name", str, "pdf_chunks", "The new CSV to write (no .csv extension)."),
            _p("source_label", str, "", "Tags each row's origin (defaults to the collection name)."),
            _p("chunk_words", int, 250, "Target words per chunk."),
            _p("overlap_words", int, 40, "Words of overlap between consecutive chunks."),
            _p("enrich", bool, True, "Look DOI-named PDFs up on Crossref for clean metadata."),
        ),
        roots=("csv", "pdf"),
    ),
]

# --------------------------------------------------------------------------- #
# Annotation -- add a column to the source CSV, in place
# --------------------------------------------------------------------------- #
ANNOTATION_FUNCTIONS = [
    Function(
        name="embed_text",
        category="annotation",
        impl="App.Backend.annotation:embed_text",
        label="Embed text",
        summary="Embed a text column into semantic vectors",
        description=(
            "[Annotation] Compute a semantic embedding vector for each row's `text_column` "
            "and store it (stringified) in the new column, editing the CSV in place. This is "
            "the foundation for semantic search, dimensionality reduction and clustering. "
            "Slow on large datasets. Queues a background task and returns its task_id."
        ),
        params=(
            CSV_NAME,
            TEXT_COLUMN,
            _p("new_column_name", str, "text_embedding", "The new column to write the vectors to.",
               form="output_column", api="embedding_column"),
            _p("model_name", str, "allenai/specter2_base", "The sentence-transformers model to embed with.",
               api="model"),
        ),
        api_path="embed_text",   # the one endpoint published with an underscore
    ),
    Function(
        name="reduce_dimensionality",
        category="annotation",
        impl="App.Backend.annotation:reduce_dimensionality",
        label="Reduce dimensionality",
        summary="Reduce embeddings to fewer dimensions with UMAP",
        description=(
            "[Annotation] Run UMAP to compress the high-dimensional embeddings in "
            "`embedding_column` down to `n_components` dimensions, written to the output "
            "column as stringified coordinates. Use n=2 for a plottable \"2d\" map, or n=5 "
            "as the \"5d\" input to clustering. Queues a background task and returns its task_id."
        ),
        params=(
            CSV_NAME,
            _p("embedding_column", str, "text_embedding", "The column holding the stored embeddings."),
            _p("new_column_name", str, "2d", "The new column to write the reduced coordinates to.",
               form="output_column", api="output_column", required=True),
            _p("n_components", int, 2, "Target number of dimensions (2 to plot, 5 to cluster).", required=True),
        ),
    ),
    Function(
        name="cluster",
        category="annotation",
        impl="App.Backend.annotation:cluster",
        label="Cluster",
        summary="Cluster rows into topics with HDBSCAN",
        description=(
            "[Annotation] Group rows into topics with HDBSCAN over the coordinates in the "
            "coordinate column (e.g. the \"5d\" UMAP column), writing a topic id per row into "
            "the output column. Larger min_cluster_size/min_samples yield fewer, tighter "
            "topics; id -1 is noise, not a topic. Queues a background task and returns its task_id."
        ),
        params=(
            CSV_NAME,
            _p("embedding_column", str, "5d", "The column of coordinates to cluster.",
               api="coordinate_column"),
            _p("new_column_name", str, "topic_id", "The new column to write topic ids to.",
               form="output_column", api="output_column"),
            _p("min_cluster_size", int, 32, "Fewest documents that can form a topic."),
            _p("min_samples", int, 8, "How conservative the clustering is (higher = more noise)."),
        ),
    ),
    Function(
        name="keyword_score",
        category="annotation",
        impl="App.Backend.annotation:keyword_score",
        label="Keyword score",
        summary="Score rows by keyword (TF-IDF) relevance to a query",
        description=(
            "[Annotation] Score every row for lexical relevance to `query` via TF-IDF cosine "
            "similarity over `text_column`, writing a 0-1 score into the new column. Rewards "
            "exact word overlap. Pair with semantic_score + hybrid_score for the best "
            "retrieval. Queues a background task and returns its task_id."
        ),
        params=(
            CSV_NAME,
            _p("query", str, "", "The search query to score against.", required=True),
            TEXT_COLUMN,
            _p("new_column_name", str, "kw", "The new column to write the score to.", form="output_column"),
        ),
    ),
    Function(
        name="semantic_score",
        category="annotation",
        impl="App.Backend.annotation:semantic_score",
        label="Semantic score",
        summary="Score rows by semantic (meaning) relevance to a query",
        description=(
            "[Annotation] Score every row for meaning-based relevance to `query` by cosine "
            "similarity between the query's embedding and each row's stored "
            "`embedding_column`, writing a score into the new column. Catches paraphrases "
            "keyword search misses (requires embed_text first). Queues a background task and "
            "returns its task_id."
        ),
        params=(
            CSV_NAME,
            _p("query", str, "", "The search query to score against.", required=True),
            _p("embedding_column", str, "text_embedding", "The column holding the stored embeddings."),
            _p("new_column_name", str, "sem", "The new column to write the score to.", form="output_column"),
        ),
    ),
    Function(
        name="hybrid_score",
        category="annotation",
        impl="App.Backend.annotation:hybrid_score",
        label="Hybrid score",
        summary="Fuse keyword and semantic scores into one relevance score",
        description=(
            "[Annotation] Fuse a keyword-score column and a semantic-score column into one "
            "combined 0-1 relevance score (Reciprocal Rank Fusion) in the new column, "
            "balancing exact-match and meaning-based retrieval. Run after keyword_score and "
            "semantic_score. Queues a background task and returns its task_id."
        ),
        params=(
            CSV_NAME,
            _p("keyword_col", str, "kw", "The keyword-score column."),
            _p("semantic_col", str, "sem", "The semantic-score column."),
            _p("new_column_name", str, "hybrid", "The new column to write the fused score to.",
               form="output_column"),
        ),
    ),
    Function(
        name="word_frequency",
        category="annotation",
        impl="App.Backend.annotation:word_frequency",
        label="Word frequency (per row)",
        summary="Annotate each row with a word-count dictionary",
        description=(
            "[Annotation] Annotate each row with its own {word: count} dictionary from "
            "`text_column` (lemmatized, stop-word filtered), stored in the new column. Set "
            "`ngram`=2 or 3 to count phrases instead of single words. Feed the result to "
            "aggregate_dictionary for a corpus-wide word table. Queues a background task and "
            "returns its task_id."
        ),
        params=(
            CSV_NAME,
            TEXT_COLUMN,
            _p("new_column_name", str, "word_freq", "The new column to write the dictionary to."),
            _p("ngram", int, 1, "1 counts words; 2 or 3 count phrases."),
        ),
    ),
    Function(
        name="label_topics",
        category="annotation",
        impl="App.Backend.annotation:label_topics",
        label="Label topics",
        summary="Label each topic with its top keywords",
        description=(
            "[Annotation] Add a column (default Topic_Label) mapping each row's topic to that "
            "topic's top `top_n` keywords, so charts can group by readable labels instead of "
            "raw topic numbers. Run after cluster. Queues a background task and returns its task_id."
        ),
        params=(
            CSV_NAME,
            TOPIC_COLUMN,
            TEXT_COLUMN,
            _p("new_column_name", str, "Topic_Label", "The new column to write the labels to."),
            # Hidden from the dashboard form on purpose: the form's `top_n` field is the
            # charts' "keep the largest N categories" (default 25), which would mean 25
            # keywords per topic label here.
            _p("top_n", int, 3, "How many keywords make up each topic's label.", form=NO_FORM),
        ),
    ),
    Function(
        name="text_length",
        category="annotation",
        impl="App.Backend.annotation:text_length",
        label="Text length",
        summary="Add a text-length column (words or chars)",
        description=(
            "[Annotation] Add a numeric column with the length of `text_column`, measured in "
            "`unit`=\"words\" or \"chars\" -- e.g. a scatter-plot axis of abstract length vs. "
            "favorability. Queues a background task and returns its task_id."
        ),
        params=(
            CSV_NAME,
            TEXT_COLUMN,
            _p("new_column_name", str, "length", "The new column to write the length to."),
            _p("unit", str, "words", "\"words\" or \"chars\"."),
        ),
    ),
    Function(
        name="extract_year",
        category="annotation",
        impl="App.Backend.annotation:extract_year",
        label="Extract year",
        summary="Extract a four-digit year from a date column",
        description=(
            "[Annotation] Parse a four-digit year out of `date_column` into a new numeric "
            "column, unlocking temporal charts (e.g. publications per year). Queues a "
            "background task and returns its task_id."
        ),
        params=(
            CSV_NAME,
            _p("date_column", str, "publish_time", "The column holding the date."),
            _p("new_column_name", str, "year", "The new column to write the year to."),
        ),
    ),
    Function(
        name="to_date",
        category="annotation",
        impl="App.Backend.annotation:to_date",
        label="To date (ISO-8601)",
        summary="Normalize a column to ISO-8601 dates",
        description=(
            "[Annotation] Normalize `date_column` into a canonical ISO-8601 (YYYY-MM-DD) date "
            "column that sorts chronologically and supports date range/threshold filtering "
            "(via numerical_filter) and time-axis charts. Queues a background task and returns "
            "its task_id."
        ),
        params=(
            CSV_NAME,
            _p("date_column", str, "publish_time", "The column holding the date."),
            _p("new_column_name", str, "date", "The new column to write the ISO date to."),
        ),
    ),
    Function(
        name="normalize_column",
        category="annotation",
        impl="App.Backend.annotation:normalize_column",
        label="Normalize column",
        summary="Min-max scale a numeric column to 0-1",
        description=(
            "[Annotation] Min-max scale `value_column` into the 0-1 range. A blank (or equal) "
            "new column name overwrites `value_column` in place; otherwise the scaled values "
            "land in a new column. Queues a background task and returns its task_id."
        ),
        params=(
            CSV_NAME,
            _p("value_column", str, "", "The numeric column to scale.", required=True),
            _p("new_column_name", str, "", "The new column (blank overwrites `value_column`)."),
        ),
    ),
    Function(
        name="hierarchical_cluster",
        category="annotation",
        impl="App.Backend.annotation:hierarchical_cluster",
        label="Hierarchical cluster",
        summary="Agglomerate topics into hierarchical super-clusters",
        description=(
            "[Annotation] Agglomerate an existing `topic_column` into `n_clusters` broader "
            "hierarchical super-clusters, writing each row's super-cluster id into "
            "`output_column`. Each topic is reduced to the centroid of its members' "
            "`embedding_column` vectors, the centroids are Ward-linked, and the tree is cut "
            "into `n_clusters` groups -- a coarser, top-down complement to HDBSCAN's flat "
            "cluster, where every topic lands in a theme (only noise stays -1). Queues a "
            "background task and returns its task_id."
        ),
        params=(
            CSV_NAME,
            TOPIC_COLUMN,
            _p("embedding_column", str, "5d", "The coordinates each topic's centroid is built from."),
            _p("output_column", str, "hcluster", "The new column to write super-cluster ids to."),
            _p("n_clusters", int, 10, "How many super-clusters to cut the tree into."),
        ),
    ),
]

# --------------------------------------------------------------------------- #
# Distillation -- write a new, derived CSV
# --------------------------------------------------------------------------- #
DISTILLATION_FUNCTIONS = [
    Function(
        name="numerical_filter",
        category="distillation",
        impl="App.Backend.distillation:numerical_filter",
        label="Numerical filter",
        summary="Filter rows above a numeric or date threshold into a new CSV",
        description=(
            "[Distillation] Keep only rows whose `target_score_column` is >= `threshold` "
            "(numeric, or an ISO-8601 date for chronological filtering), writing them sorted "
            "best-first to a new `output_csv`. Great for isolating the most relevant papers. "
            "Queues a background task and returns its task_id."
        ),
        params=(
            # The dashboard form has one CSV picker (`csv_name`); it feeds `source_csv` when
            # the user has not typed a separate source. REST published this as `csv_name`
            # and MCP as `source_csv` -- both are live, so both are honoured.
            _p("source_csv", str, lambda c: c["csv_name"], "The CSV dataset to filter.",
               api="csv_name", mcp="source_csv", required=True),
            _out_csv("Filtered_Output"),
            _p("target_score_column", str, "hybrid", "The numeric or ISO-date column to threshold."),
            _p("threshold", float, 0.7, "Keep rows whose column value is >= this."),
        ),
    ),
    Function(
        name="categorical_filter",
        category="distillation",
        impl="App.Backend.distillation:categorical_filter",
        label="Categorical filter",
        summary="Keep rows exactly matching a category value",
        description=(
            "[Distillation] Keep only rows whose `target_column` exactly equals "
            "`expected_value` (compared as text) into a new `output_csv` -- e.g. isolate a "
            "single topic. Queues a background task and returns its task_id."
        ),
        params=(
            SOURCE_CSV,
            _out_csv("Filtered_Output"),
            _p("target_column", str, "", "The column to match on.", required=True),
            _p("expected_value", str, "", "The value that column must equal.", required=True),
        ),
    ),
    Function(
        name="combine_csvs",
        category="distillation",
        impl="App.Backend.distillation:combine_csvs",
        label="Combine CSVs",
        summary="Stack several CSVs into one, tagged by origin",
        description=(
            "[Distillation] Stack the comma-separated `source_csvs` into one CSV, adding "
            "`source_column` that tags each row with the file it came from. Queues a "
            "background task and returns its task_id."
        ),
        params=(
            _p("source_csvs", str, "", "Comma-separated CSV names to stack.", required=True),
            _out_csv("Combined_Corpus"),
            _p("source_column", str, "source", "The new column tagging each row's origin."),
        ),
    ),
    Function(
        name="aggregate_dictionary",
        category="distillation",
        impl="App.Backend.distillation:aggregate_dictionary",
        label="Aggregate dictionary",
        summary="Sum per-row dictionaries into a corpus-wide table",
        description=(
            "[Distillation] Sum the per-row {key: number} dictionaries in `dict_column` across "
            "every row into a new [key, sum] CSV sorted by total. Pairs with word_frequency to "
            "build a corpus-wide frequency table ready for a bar chart. Queues a background "
            "task and returns its task_id."
        ),
        params=(
            SOURCE_CSV,
            _out_csv("Aggregated_Counts"),
            _p("dict_column", str, "word_freq", "The column of stringified {key: number} dicts."),
        ),
    ),
    Function(
        name="group_aggregate",
        category="distillation",
        impl="App.Backend.distillation:group_aggregate",
        label="Group aggregate",
        summary="Group rows and aggregate into a summary CSV",
        description=(
            "[Distillation] Group by `group_column` (comma-separate it for multi-dimensional "
            "counts) and aggregate: count rows, or apply mean/sum/min/max to `value_column`. "
            "`exclude` drops comma-separated group values (e.g. \"-1\"). Queues a background "
            "task and returns its task_id."
        ),
        params=(
            SOURCE_CSV,
            _out_csv("Grouped_Output"),
            _p("group_column", str, "", "The column(s) to group by (comma-separated).", required=True),
            _p("value_column", str, "", "The column to aggregate (blank counts rows)."),
            _p("agg", str, "count", "count | mean | sum | min | max."),
            EXCLUDE,
        ),
    ),
    Function(
        name="top_n_by_column",
        category="distillation",
        impl="App.Backend.distillation:top_n_by_column",
        label="Top N by column",
        summary="Keep the top N rows by a column",
        description=(
            "[Distillation] Sort by `sort_column` and keep the top `n` rows into a new CSV "
            "(`ascending=true` keeps the smallest). Threshold-free, unlike numerical_filter. "
            "Queues a background task and returns its task_id."
        ),
        params=(
            SOURCE_CSV,
            _out_csv("Top_N_Output"),
            _p("sort_column", str, "", "The column to sort by.", required=True),
            _p("n", int, 100, "How many rows to keep."),
            _p("ascending", bool, False, "Keep the smallest instead of the largest."),
        ),
    ),
    Function(
        name="deduplicate",
        category="distillation",
        impl="App.Backend.distillation:deduplicate",
        label="Deduplicate",
        summary="Drop rows repeating a value in a column",
        description=(
            "[Distillation] Drop rows that repeat a value in `subset_column` (keeping the "
            "first) into a new CSV -- e.g. dedupe papers by title or doi. Queues a background "
            "task and returns its task_id."
        ),
        params=(
            SOURCE_CSV,
            _out_csv("Deduplicated_Output"),
            _p("subset_column", str, "", "The column whose repeats are dropped.", required=True),
        ),
    ),
    Function(
        name="select_columns",
        category="distillation",
        impl="App.Backend.distillation:select_columns",
        label="Select columns",
        summary="Keep or drop a subset of columns",
        description=(
            "[Distillation] Write a new CSV keeping only the comma-separated `columns` (or, "
            "with `drop=true`, everything except them). Handy for stripping a heavy embedding "
            "column before export. Queues a background task and returns its task_id."
        ),
        params=(
            SOURCE_CSV,
            _out_csv("Selected_Columns_Output"),
            _p("columns", str, "", "Comma-separated column names.", required=True),
            _p("drop", bool, False, "Drop these columns instead of keeping only them."),
        ),
    ),
    Function(
        name="cross_tab",
        category="distillation",
        impl="App.Backend.distillation:cross_tab",
        label="Cross tab",
        summary="Build a contingency count matrix (for a heatmap)",
        description=(
            "[Distillation] Count how many rows fall into each (`row_column`, `column_column`) "
            "pairing, as a matrix CSV -- the shape a heatmap expects. Queues a background task "
            "and returns its task_id."
        ),
        params=(
            SOURCE_CSV,
            _out_csv("Cross_Tab_Output"),
            _p("row_column", str, "", "The column forming the matrix's rows.", required=True),
            _p("column_column", str, "", "The column forming the matrix's columns.", required=True),
        ),
    ),
    Function(
        name="arithmetic",
        category="distillation",
        impl="App.Backend.distillation:arithmetic",
        label="Arithmetic",
        summary="Compute a new column via column arithmetic",
        description=(
            "[Distillation] Write `new_column = column_a <operation> operand` "
            "(add/subtract/multiply/divide) to a new CSV, where `operand` is another column or "
            "a numeric constant. With `group_by`, a column operand becomes its per-group SUM, "
            "so count/count grouped by a category gives each row's share of its group (x100 = "
            "percent). Queues a background task and returns its task_id."
        ),
        params=(
            SOURCE_CSV,
            _out_csv("Arithmetic_Output"),
            _p("column_a", str, "", "The left-hand column.", required=True),
            _p("operation", str, "divide", "add | subtract | multiply | divide.", required=True),
            _p("operand", str, "", "Another column name, or a numeric constant.", required=True),
            _p("new_column", str, "result", "The new column to write the result to.",
               form="new_column_name"),
            _p("group_by", str, "", "Sum a column operand within each group of this column."),
        ),
    ),
]

# --------------------------------------------------------------------------- #
# Visualization -- render an HTML chart (terminal; produces no new column/CSV)
# --------------------------------------------------------------------------- #
VISUALIZATION_FUNCTIONS = [
    Function(
        name="bar_chart",
        category="visualization",
        impl="App.Backend.visualization:bar_chart",
        label="Bar chart",
        summary="Render a bar chart",
        description=(
            "[Visualization] Render a bar chart (HTML): with no `value_column` it counts the "
            "frequency of each `category_column` value, with one it sums that value per "
            "category. `series_column` splits bars into grouped sub-bars; `top_n` keeps the "
            "largest categories; `exclude` drops comma-separated categories. Queues a "
            "background task and returns its task_id."
        ),
        params=(
            CSV_NAME,
            _p("category_column", str, "", "The column whose values become the bars.", required=True),
            _p("value_column", str, "", "Sum this column per category (blank counts rows)."),
            _p("series_column", str, "", "Split each bar into grouped sub-bars by this column."),
            CHART_TITLE,
            _out_html("bar_chart", "bar_chart"),
            _p("top_n", int, 25, "Keep only the largest N categories."),
            EXCLUDE,
        ),
        roots=("csv", "html"),
    ),
    Function(
        name="scatter_plot",
        category="visualization",
        impl="App.Backend.visualization:scatter_plot",
        label="Scatter plot",
        summary="Render a scatter / bubble plot",
        description=(
            "[Visualization] Render a 2D scatter plot (HTML) from two numeric columns "
            "(`x_column`, `y_column`) or a single `coord_column` of stringified \"[x, y]\" "
            "pairs (like the \"2d\" UMAP column). `color_column` tints points by category; "
            "`size_column` scales them into a bubble chart. Queues a background task and "
            "returns its task_id."
        ),
        params=(
            CSV_NAME,
            _p("x_column", str, "", "The x axis column."),
            _p("y_column", str, "", "The y axis column."),
            _p("color_column", str, "", "Tint points by this category column."),
            _p("size_column", str, "", "Scale points by this numeric column (bubble chart)."),
            _p("coord_column", str, "", "A column of stringified \"[x, y]\" pairs, instead of x/y."),
            CHART_TITLE,
            _out_html("scatter", "scatter_plot"),
        ),
        roots=("csv", "html"),
    ),
    Function(
        name="histogram",
        category="visualization",
        impl="App.Backend.visualization:histogram",
        label="Histogram",
        summary="Render a histogram of a numeric column",
        description=(
            "[Visualization] Render a histogram (HTML) of `value_column`'s distribution across "
            "`bins` buckets. `color_column` overlays one series per category; `log_x`/`log_y` "
            "switch that axis to a logarithmic scale. Queues a background task and returns its "
            "task_id."
        ),
        params=(
            CSV_NAME,
            _p("value_column", str, "", "The numeric column to bin.", required=True),
            _p("bins", int, 30, "How many buckets to bin into."),
            CHART_TITLE,
            _out_html("histogram", "histogram"),
            _p("color_column", str, "", "Overlay one series per value of this column."),
            _p("log_x", bool, False, "Use a logarithmic x axis."),
            _p("log_y", bool, False, "Use a logarithmic y axis."),
        ),
        roots=("csv", "html"),
    ),
    Function(
        name="line_chart",
        category="visualization",
        impl="App.Backend.visualization:line_chart",
        label="Line chart",
        summary="Render a line chart over a sorted x-axis",
        description=(
            "[Visualization] Render a line chart (HTML) of `y_column` against a sorted "
            "`x_column` (e.g. paper counts per year); `color_column` draws one line per "
            "category. Pre-aggregate with group_aggregate for one point per x value. Queues a "
            "background task and returns its task_id."
        ),
        params=(
            CSV_NAME,
            _p("x_column", str, "", "The x axis column (the series is sorted by it).", required=True),
            _p("y_column", str, "", "The y axis column.", required=True),
            _p("color_column", str, "", "Draw one line per value of this column."),
            CHART_TITLE,
            _out_html("line_chart", "line_chart"),
        ),
        roots=("csv", "html"),
    ),
    Function(
        name="box_plot",
        category="visualization",
        impl="App.Backend.visualization:box_plot",
        label="Box plot",
        summary="Render a box plot of a distribution",
        description=(
            "[Visualization] Render a box plot (HTML) of `value_column`'s distribution (median, "
            "quartiles, outliers), optionally split into one box per `category_column`; "
            "`exclude` drops comma-separated categories, `log_y` uses a log y-axis. Queues a "
            "background task and returns its task_id."
        ),
        params=(
            CSV_NAME,
            _p("value_column", str, "", "The numeric column whose spread is drawn.", required=True),
            _p("category_column", str, "", "Draw one box per value of this column."),
            CHART_TITLE,
            _out_html("box_plot", "box_plot"),
            EXCLUDE,
            _p("log_y", bool, False, "Use a logarithmic y axis."),
        ),
        roots=("csv", "html"),
    ),
    Function(
        name="heatmap",
        category="visualization",
        impl="App.Backend.visualization:heatmap",
        label="Heatmap",
        summary="Render a heatmap (density or mean)",
        description=(
            "[Visualization] Render a heatmap (HTML): with no `value_column` it shows the count "
            "density of (x, y) pairs; with one, the mean of `value_column` per (x, y) cell. "
            "Queues a background task and returns its task_id."
        ),
        params=(
            CSV_NAME,
            _p("x_column", str, "", "The column forming the x axis.", required=True),
            _p("y_column", str, "", "The column forming the y axis.", required=True),
            _p("value_column", str, "", "Show the mean of this column per cell (blank = density)."),
            CHART_TITLE,
            _out_html("heatmap", "heatmap"),
        ),
        roots=("csv", "html"),
    ),
    Function(
        name="pie_chart",
        category="visualization",
        impl="App.Backend.visualization:pie_chart",
        label="Pie chart",
        summary="Render a pie chart of category shares",
        description=(
            "[Visualization] Render a pie chart (HTML) of category proportions by row count or "
            "summed `value_column`; `top_n` keeps the largest slices, `exclude` drops "
            "comma-separated categories. Queues a background task and returns its task_id."
        ),
        params=(
            CSV_NAME,
            _p("category_column", str, "", "The column whose values become the slices.", required=True),
            _p("value_column", str, "", "Sum this column per category (blank counts rows)."),
            CHART_TITLE,
            _out_html("pie_chart", "pie_chart"),
            _p("top_n", int, 10, "Keep only the largest N slices."),
            EXCLUDE,
        ),
        roots=("csv", "html"),
    ),
    Function(
        name="distance_map",
        category="visualization",
        impl="App.Backend.visualization:distance_map",
        label="Distance map",
        summary="Render an intertopic distance map",
        description=(
            "[Visualization] Render an intertopic distance map (HTML): one bubble per topic "
            "positioned at its mean 2D coordinate, sized by document count and labelled with "
            "its top keywords. Needs a coordinate column of \"[x, y]\" pairs and a "
            "`topic_column`. Queues a background task and returns its task_id."
        ),
        params=(
            CSV_NAME,
            TOPIC_COLUMN,
            TEXT_COLUMN,
            _p("coord_column", str, "2d", "The column of stringified \"[x, y]\" pairs.",
               form="embedding_column", api="coordinate_column"),
            _out_html("Topics", "Space_Biology_Topics"),
            CHART_TITLE,
        ),
        roots=("csv", "html"),
    ),
    Function(
        name="hierarchical_dendrogram",
        category="visualization",
        impl="App.Backend.visualization:hierarchical_dendrogram",
        label="Hierarchical dendrogram",
        summary="Render a hierarchical topic dendrogram",
        description=(
            "[Visualization] Render an HTML dendrogram of a corpus's topics: each topic is "
            "reduced to the mean of its members' `embedding_column` vectors, the centroids are "
            "joined bottom-up with Ward hierarchical clustering, and the tree shows which "
            "topics fuse into broader super-themes. Keeps the `top_n` largest topics so the "
            "tree stays legible; leaves are labelled with each topic's top keywords + size; "
            "noise (-1) is excluded. Queues a background task and returns its task_id."
        ),
        params=(
            CSV_NAME,
            TOPIC_COLUMN,
            TEXT_COLUMN,
            _p("embedding_column", str, "5d", "The coordinates each topic's centroid is built from."),
            _out_html("Dendrogram", "Topic_Dendrogram"),
            CHART_TITLE,
            _p("top_n", int, 30, "Keep only the largest N topics."),
            _p("orientation", str, "left", "left | right | bottom | top."),
        ),
        roots=("csv", "html"),
    ),
]

ALL_FUNCTIONS: list[Function] = (
    IMPORT_FUNCTIONS + ANNOTATION_FUNCTIONS + DISTILLATION_FUNCTIONS + VISUALIZATION_FUNCTIONS
)

REGISTRY: dict[str, Function] = {fn.name: fn for fn in ALL_FUNCTIONS}


def get(name: str) -> Function:
    fn = REGISTRY.get(name)
    if fn is None:
        raise KeyError(f"Unknown pipeline function {name!r}.")
    return fn


def by_category(category: str) -> list[Function]:
    return [fn for fn in ALL_FUNCTIONS if fn.category == category]


def _self_check() -> None:
    """Catch a malformed entry at import time rather than when a task runs."""
    for fn in ALL_FUNCTIONS:
        if fn.category not in CATEGORIES:
            raise ValueError(f"{fn.name}: unknown category {fn.category!r}")
        if ":" not in fn.impl:
            raise ValueError(f"{fn.name}: impl must be 'module.path:attribute'")
        fn.output_param  # every function must declare the param naming its output
        names = [p.name for p in fn.params]
        if len(names) != len(set(names)):
            raise ValueError(f"{fn.name}: duplicate param names {names}")
        api_names = [p.api_name for p in fn.params]
        if len(api_names) != len(set(api_names)):
            raise ValueError(f"{fn.name}: duplicate API param names {api_names}")


_self_check()
