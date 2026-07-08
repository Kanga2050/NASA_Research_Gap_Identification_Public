"""Machine-readable node manifest for the Studio visual-scripting editor.

Each entry describes one backend function as a graph node: its category, the
form field that receives the *source table* (`table_param`), its typed **column
input ports** (`columns`), inline **preference fields** (`prefs`), and what it
**produces** (`output`). The manifest is the single source of truth the editor
uses to render nodes, populate dependent (typed) column dropdowns and validate
wire types; the Run compiler (`views.studio_run`) reads the same entries to map a
node back onto `TASK_SPECS` and queue it, so positional-arg order stays owned by
`TASK_SPECS` and the critical cross-entry-point invariant is preserved.

Wire types: "text" | "number" | "date" | "embedding" (see data_lookups.infer_column_type).
`table_out`: "same" (annotation mutates its input CSV), "new" (distillation writes
a fresh CSV), "none" (visualization). `projects`: how a node's output columns are
predicted for downstream dropdowns -- "passthrough" (keeps input columns, plus any
added column) or "replace" (new, unpredictable schema -> downstream uses free text).
"""
from __future__ import annotations

import json

CATEGORICAL = ["text", "number", "date"]
AXIS = ["number", "date", "text"]


def _n(action, label, category, *, table_param, table_out, columns=None, prefs=None,
       output=None, projects="passthrough"):
    return {
        "action": action,
        "label": label,
        "category": category,
        "table_param": table_param,
        "table_out": table_out,
        "projects": projects,
        "columns": columns or [],
        "prefs": prefs or [],
        "output": output,
    }


def _col(param, label, accepts):
    return {"param": param, "label": label, "accepts": accepts}


def _pref(param, label, widget, default=None, options=None, placeholder=""):
    return {"param": param, "label": label, "widget": widget, "default": default,
            "options": options or [], "placeholder": placeholder}


def _out(param, label, kind, wire_type=None, default=""):
    # kind: "column" (annotation adds a column), "csv" (distillation), "html" (viz).
    return {"param": param, "label": label, "kind": kind, "type": wire_type, "default": default}


# ---- Source / import nodes (no table input) ----
SOURCE_NODES = [
    {"action": "__csv__", "label": "CSV Input", "category": "source",
     "table_param": None, "table_out": "new", "projects": "replace",
     "columns": [], "prefs": [], "output": None},
    _n("openalex_scraper", "OpenAlex Import", "source",
       table_param=None, table_out="new", projects="replace",
       prefs=[_pref("topic", "Topic", "text", "space biology"),
              _pref("limit", "Max papers", "number", 10000)],
       output=_out("csv_name", "Output CSV", "csv", default="scraped")),
]

# ---- Annotation nodes (mutate the source CSV in place, adding a column) ----
ANNOTATION_NODES = [
    _n("embed_text", "Embed Text", "annotation", table_param="csv_name", table_out="same",
       columns=[_col("text_column", "Text", ["text"])],
       prefs=[_pref("model_name", "Model", "text", "allenai/specter2_base")],
       output=_out("output_column", "Embedding column", "column", "embedding", "abstract_embedding")),
    _n("reduce_dimensionality", "Reduce Dimensionality", "annotation", table_param="csv_name", table_out="same",
       columns=[_col("embedding_column", "Embedding", ["embedding"])],
       prefs=[_pref("n_components", "Components", "number", 2)],
       output=_out("output_column", "Reduced column", "column", "embedding", "2d")),
    _n("cluster", "Cluster", "annotation", table_param="csv_name", table_out="same",
       columns=[_col("embedding_column", "Embedding", ["embedding"])],
       prefs=[_pref("min_cluster_size", "Min cluster size", "number", 32),
              _pref("min_samples", "Min samples", "number", 8)],
       output=_out("output_column", "Topic column", "column", "number", "topic_id")),
    _n("keyword_score", "Keyword Score", "annotation", table_param="csv_name", table_out="same",
       columns=[_col("text_column", "Text", ["text"])],
       prefs=[_pref("query", "Query", "text", "", placeholder="search terms")],
       output=_out("output_column", "Score column", "column", "number", "kw")),
    _n("semantic_score", "Semantic Score", "annotation", table_param="csv_name", table_out="same",
       columns=[_col("embedding_column", "Embedding", ["embedding"])],
       prefs=[_pref("query", "Query", "text", "", placeholder="natural-language query")],
       output=_out("output_column", "Score column", "column", "number", "sem")),
    _n("hybrid_score", "Hybrid Score", "annotation", table_param="csv_name", table_out="same",
       columns=[_col("keyword_col", "Keyword score", ["number"]),
                _col("semantic_col", "Semantic score", ["number"])],
       output=_out("output_column", "Score column", "column", "number", "hybrid")),
    _n("word_frequency", "Word Frequency", "annotation", table_param="csv_name", table_out="same",
       columns=[_col("text_column", "Text", ["text"])],
       prefs=[_pref("ngram", "N-gram", "number", 1)],
       output=_out("new_column_name", "Freq column", "column", "text", "word_freq")),
    _n("label_topics", "Label Topics", "annotation", table_param="csv_name", table_out="same",
       columns=[_col("topic_column", "Topic id", ["number", "text"]),
                _col("text_column", "Text", ["text"])],
       output=_out("new_column_name", "Label column", "column", "text", "Topic_Label")),
    _n("text_length", "Text Length", "annotation", table_param="csv_name", table_out="same",
       columns=[_col("text_column", "Text", ["text"])],
       prefs=[_pref("unit", "Unit", "select", "words", ["words", "chars"])],
       output=_out("new_column_name", "Length column", "column", "number", "length")),
    _n("extract_year", "Extract Year", "annotation", table_param="csv_name", table_out="same",
       columns=[_col("date_column", "Date", ["text", "date"])],
       output=_out("new_column_name", "Year column", "column", "number", "year")),
    _n("to_date", "To Date (ISO)", "annotation", table_param="csv_name", table_out="same",
       columns=[_col("date_column", "Date-ish", ["text", "date"])],
       output=_out("new_column_name", "Date column", "column", "date", "date")),
    _n("normalize_column", "Normalize Column", "annotation", table_param="csv_name", table_out="same",
       columns=[_col("value_column", "Value", ["number"])],
       output=_out("new_column_name", "Normalized column (blank = in place)", "column", "number", "")),
]

# ---- Distillation nodes (read a source CSV, write a new CSV) ----
DISTILLATION_NODES = [
    _n("numerical_filter", "Numeric / Date Filter", "distillation", table_param="source_csv", table_out="new",
       columns=[_col("target_score_column", "Filter on", ["number", "date"])],
       prefs=[_pref("threshold", "Min threshold", "text", "0.7", placeholder="0.7 or 2015-01-01")],
       output=_out("output_csv", "Output CSV", "csv", default="Filtered_Output")),
    _n("categorical_filter", "Categorical Filter", "distillation", table_param="source_csv", table_out="new",
       columns=[_col("target_column", "Column", CATEGORICAL)],
       prefs=[_pref("expected_value", "Equals value", "text", "")],
       output=_out("output_csv", "Output CSV", "csv", default="Filtered_Output")),
    _n("deduplicate", "Deduplicate", "distillation", table_param="source_csv", table_out="new",
       columns=[_col("subset_column", "Dedup on", CATEGORICAL)],
       output=_out("output_csv", "Output CSV", "csv", default="Deduplicated_Output")),
    _n("top_n_by_column", "Top N By Column", "distillation", table_param="source_csv", table_out="new",
       columns=[_col("sort_column", "Sort by", ["number", "date"])],
       prefs=[_pref("n", "N", "number", 100), _pref("ascending", "Ascending", "checkbox", False)],
       output=_out("output_csv", "Output CSV", "csv", default="Top_N_Output")),
    _n("select_columns", "Select Columns", "distillation", table_param="source_csv", table_out="new",
       prefs=[_pref("columns", "Columns (comma-sep)", "text", ""),
              _pref("drop", "Drop instead of keep", "checkbox", False)],
       output=_out("output_csv", "Output CSV", "csv", default="Selected_Columns_Output")),
    _n("arithmetic", "Arithmetic", "distillation", table_param="source_csv", table_out="new",
       columns=[_col("column_a", "Column A", ["number"])],
       prefs=[_pref("operation", "Operation", "select", "divide", ["add", "subtract", "multiply", "divide"]),
              _pref("operand", "Operand (column or number)", "text", ""),
              _pref("new_column_name", "New column", "text", "result"),
              _pref("group_by", "Group by (optional)", "text", "")],
       output=_out("output_csv", "Output CSV", "csv", default="Arithmetic_Output")),
    _n("group_aggregate", "Group Aggregate", "distillation", table_param="source_csv", table_out="new",
       projects="replace",
       columns=[_col("group_column", "Group by", CATEGORICAL), _col("value_column", "Value (optional)", ["number"])],
       prefs=[_pref("agg", "Aggregation", "select", "count", ["count", "mean", "sum", "min", "max"]),
              _pref("exclude", "Exclude values", "text", "")],
       output=_out("output_csv", "Output CSV", "csv", default="Grouped_Output")),
    _n("cross_tab", "Cross Tab", "distillation", table_param="source_csv", table_out="new",
       projects="replace",
       columns=[_col("row_column", "Rows", CATEGORICAL), _col("column_column", "Columns", CATEGORICAL)],
       output=_out("output_csv", "Output CSV", "csv", default="Cross_Tab_Output")),
    _n("aggregate_dictionary", "Aggregate Dictionary", "distillation", table_param="source_csv", table_out="new",
       projects="replace",
       columns=[_col("dict_column", "Dict column", ["text"])],
       output=_out("output_csv", "Output CSV", "csv", default="Aggregated_Counts")),
    _n("combine_csvs", "Combine CSVs", "distillation", table_param=None, table_out="new", projects="replace",
       prefs=[_pref("source_csvs", "CSVs (comma-sep)", "text", ""),
              _pref("source_column", "Source tag column", "text", "source")],
       output=_out("output_csv", "Output CSV", "csv", default="Combined_Corpus")),
]

# ---- Visualization nodes (read a CSV, write an HTML chart -- terminal) ----
VISUALIZATION_NODES = [
    _n("bar_chart", "Bar Chart", "visualization", table_param="csv_name", table_out="none",
       columns=[_col("category_column", "Category", CATEGORICAL), _col("value_column", "Value (optional)", ["number"]),
                _col("series_column", "Series (optional)", CATEGORICAL)],
       prefs=[_pref("chart_title", "Title", "text", ""), _pref("top_n", "Top N", "number", 25),
              _pref("exclude", "Exclude values", "text", "")],
       output=_out("output_name", "Output HTML", "html", default="bar_chart")),
    _n("histogram", "Histogram", "visualization", table_param="csv_name", table_out="none",
       columns=[_col("value_column", "Value", ["number", "date"]), _col("color_column", "Color (optional)", CATEGORICAL)],
       prefs=[_pref("bins", "Bins", "number", 30), _pref("chart_title", "Title", "text", ""),
              _pref("log_x", "Log X", "checkbox", False), _pref("log_y", "Log Y", "checkbox", False)],
       output=_out("output_name", "Output HTML", "html", default="histogram")),
    _n("scatter_plot", "Scatter Plot", "visualization", table_param="csv_name", table_out="none",
       columns=[_col("x_column", "X", AXIS), _col("y_column", "Y", AXIS), _col("color_column", "Color", CATEGORICAL),
                _col("size_column", "Size", ["number"]), _col("coord_column", "Coord (2d embedding)", ["embedding"])],
       prefs=[_pref("chart_title", "Title", "text", "")],
       output=_out("output_name", "Output HTML", "html", default="scatter")),
    _n("line_chart", "Line Chart", "visualization", table_param="csv_name", table_out="none",
       columns=[_col("x_column", "X", AXIS), _col("y_column", "Y", ["number"]), _col("color_column", "Color", CATEGORICAL)],
       prefs=[_pref("chart_title", "Title", "text", "")],
       output=_out("output_name", "Output HTML", "html", default="line_chart")),
    _n("box_plot", "Box Plot", "visualization", table_param="csv_name", table_out="none",
       columns=[_col("value_column", "Value", ["number"]), _col("category_column", "Category", CATEGORICAL)],
       prefs=[_pref("chart_title", "Title", "text", ""), _pref("exclude", "Exclude values", "text", ""),
              _pref("log_y", "Log Y", "checkbox", False)],
       output=_out("output_name", "Output HTML", "html", default="box_plot")),
    _n("heatmap", "Heatmap", "visualization", table_param="csv_name", table_out="none",
       columns=[_col("x_column", "X", CATEGORICAL), _col("y_column", "Y", CATEGORICAL), _col("value_column", "Value", ["number"])],
       prefs=[_pref("chart_title", "Title", "text", "")],
       output=_out("output_name", "Output HTML", "html", default="heatmap")),
    _n("pie_chart", "Pie Chart", "visualization", table_param="csv_name", table_out="none",
       columns=[_col("category_column", "Category", CATEGORICAL), _col("value_column", "Value (optional)", ["number"])],
       prefs=[_pref("chart_title", "Title", "text", ""), _pref("top_n", "Top N", "number", 10),
              _pref("exclude", "Exclude values", "text", "")],
       output=_out("output_name", "Output HTML", "html", default="pie_chart")),
    _n("distance_map", "Distance Map", "visualization", table_param="csv_name", table_out="none",
       columns=[_col("topic_column", "Topic id", ["number", "text"]), _col("text_column", "Text", ["text"]),
                _col("embedding_column", "2d coord", ["embedding"])],
       prefs=[_pref("chart_title", "Title", "text", "")],
       output=_out("output_name", "Output HTML", "html", default="Topics")),
]

ALL_NODES = SOURCE_NODES + ANNOTATION_NODES + DISTILLATION_NODES + VISUALIZATION_NODES

# Keyed by action for the Run compiler.
MANIFEST = {node["action"]: node for node in ALL_NODES}

# Palette groups for the editor sidebar.
PALETTE = [
    {"category": "source", "label": "Inputs", "nodes": [n["action"] for n in SOURCE_NODES]},
    {"category": "annotation", "label": "Annotation", "nodes": [n["action"] for n in ANNOTATION_NODES]},
    {"category": "distillation", "label": "Distillation", "nodes": [n["action"] for n in DISTILLATION_NODES]},
    {"category": "visualization", "label": "Visualization", "nodes": [n["action"] for n in VISUALIZATION_NODES]},
]


def manifest_json() -> str:
    return json.dumps({"nodes": MANIFEST, "palette": PALETTE})
