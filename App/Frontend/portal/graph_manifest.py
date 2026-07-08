"""Machine-readable node manifest for the Studio visual-scripting editor.

Wire model (two kinds of wire):
  * **csv**    — carries a whole table (a CSV name).
  * **column** — carries one column of a CSV, plus its data type
                 ("text" | "number" | "date" | "embedding").

Each node has exactly one output wire, keyed by category:
  * **CSV Input**      (source)        -> csv
  * **Select Column**  (the column block: csv in, dependent column dropdown) -> column
  * **Annotation**     (column in(s))  -> column   (the newly-created column)
  * **Distillation**   (csv in + column param(s)) -> csv   (feed a Select Column to pick columns)
  * **Visualization**  (column in(s))  -> html     (terminal)

The Run compiler (`views.studio_run`) propagates "carriage" along the wires in
topological order: a column wire carries its source CSV, so a function's source
CSV is derived from its input wires. Node ports map to backend form-field names,
so the compiler reuses `TASK_SPECS` for positional-arg order (invariant preserved).
"""
from __future__ import annotations

import json

ANY = ["text", "number", "date", "embedding"]
CATEGORICAL = ["text", "number", "date"]
AXIS = ["number", "date", "text"]


def _csv_in(param, label="Table (CSV)"):
    return {"param": param, "label": label, "wire": "csv"}


def _col_in(param, label, accepts, optional=False):
    return {"param": param, "label": label, "wire": "column", "accepts": accepts, "optional": optional}


def _pref(param, label, widget, default=None, options=None, placeholder=""):
    return {"param": param, "label": label, "widget": widget, "default": default,
            "options": options or [], "placeholder": placeholder}


def _out_col(param, wire_type, default):
    return {"param": param, "kind": "column", "type": wire_type, "default": default}


def _out_csv(param, default):
    return {"param": param, "kind": "csv", "default": default}


def _out_html(param, default):
    return {"param": param, "kind": "html", "default": default}


def _n(action, label, category, *, table_param, inputs, output, prefs=None, special=None, projects=None):
    return {"action": action, "label": label, "category": category, "table_param": table_param,
            "inputs": inputs, "prefs": prefs or [], "output": output, "special": special,
            "projects": projects}


# ---- Source / bridge nodes ----
SOURCE_NODES = [
    _n("__csv__", "CSV Input", "source", table_param=None, inputs=[],
       output=_out_csv(None, ""), special="csv_input"),
    _n("__column__", "Select Column", "source", table_param=None,
       inputs=[_csv_in("__source__", "From CSV")],
       output=_out_col(None, "text", ""), special="select_column"),
    _n("openalex_scraper", "OpenAlex Import", "source", table_param=None, inputs=[],
       prefs=[_pref("topic", "Topic", "text", "space biology"),
              _pref("limit", "Max papers", "number", 10000)],
       output=_out_csv("csv_name", "scraped")),
]

# ---- Annotation nodes: column input(s) -> new column ----
ANNOTATION_NODES = [
    _n("embed_text", "Embed Text", "annotation", table_param="csv_name",
       inputs=[_col_in("text_column", "Text", ["text"])],
       prefs=[_pref("model_name", "Model", "text", "allenai/specter2_base")],
       output=_out_col("output_column", "embedding", "abstract_embedding")),
    _n("reduce_dimensionality", "Reduce Dimensionality", "annotation", table_param="csv_name",
       inputs=[_col_in("embedding_column", "Embedding", ["embedding"])],
       prefs=[_pref("n_components", "Components", "number", 2)],
       output=_out_col("output_column", "embedding", "2d")),
    _n("cluster", "Cluster", "annotation", table_param="csv_name",
       inputs=[_col_in("embedding_column", "Embedding", ["embedding"])],
       prefs=[_pref("min_cluster_size", "Min cluster size", "number", 32),
              _pref("min_samples", "Min samples", "number", 8)],
       output=_out_col("output_column", "number", "topic_id")),
    _n("keyword_score", "Keyword Score", "annotation", table_param="csv_name",
       inputs=[_col_in("text_column", "Text", ["text"])],
       prefs=[_pref("query", "Query", "text", "", placeholder="search terms")],
       output=_out_col("output_column", "number", "kw")),
    _n("semantic_score", "Semantic Score", "annotation", table_param="csv_name",
       inputs=[_col_in("embedding_column", "Embedding", ["embedding"])],
       prefs=[_pref("query", "Query", "text", "", placeholder="natural-language query")],
       output=_out_col("output_column", "number", "sem")),
    _n("hybrid_score", "Hybrid Score", "annotation", table_param="csv_name",
       inputs=[_col_in("keyword_col", "Keyword score", ["number"]),
               _col_in("semantic_col", "Semantic score", ["number"])],
       output=_out_col("output_column", "number", "hybrid")),
    _n("word_frequency", "Word Frequency", "annotation", table_param="csv_name",
       inputs=[_col_in("text_column", "Text", ["text"])],
       prefs=[_pref("ngram", "N-gram", "number", 1)],
       output=_out_col("new_column_name", "text", "word_freq")),
    _n("label_topics", "Label Topics", "annotation", table_param="csv_name",
       inputs=[_col_in("topic_column", "Topic id", ["number", "text"]),
               _col_in("text_column", "Text", ["text"])],
       output=_out_col("new_column_name", "text", "Topic_Label")),
    _n("text_length", "Text Length", "annotation", table_param="csv_name",
       inputs=[_col_in("text_column", "Text", ["text"])],
       prefs=[_pref("unit", "Unit", "select", "words", ["words", "chars"])],
       output=_out_col("new_column_name", "number", "length")),
    _n("extract_year", "Extract Year", "annotation", table_param="csv_name",
       inputs=[_col_in("date_column", "Date", ["text", "date"])],
       output=_out_col("new_column_name", "number", "year")),
    _n("to_date", "To Date (ISO)", "annotation", table_param="csv_name",
       inputs=[_col_in("date_column", "Date-ish", ["text", "date"])],
       output=_out_col("new_column_name", "date", "date")),
    _n("normalize_column", "Normalize Column", "annotation", table_param="csv_name",
       inputs=[_col_in("value_column", "Value", ["number"])],
       output=_out_col("new_column_name", "number", "")),
]

# ---- Distillation nodes: csv input (+ column params) -> new csv ----
DISTILLATION_NODES = [
    _n("numerical_filter", "Numeric / Date Filter", "distillation", table_param="source_csv",
       inputs=[_csv_in("source_csv"), _col_in("target_score_column", "Filter on", ["number", "date"])],
       prefs=[_pref("threshold", "Min threshold", "text", "0.7", placeholder="0.7 or 2015-01-01")],
       output=_out_csv("output_csv", "Filtered_Output"), projects="passthrough"),
    _n("categorical_filter", "Categorical Filter", "distillation", table_param="source_csv",
       inputs=[_csv_in("source_csv"), _col_in("target_column", "Column", CATEGORICAL)],
       prefs=[_pref("expected_value", "Equals value", "text", "")],
       output=_out_csv("output_csv", "Filtered_Output"), projects="passthrough"),
    _n("deduplicate", "Deduplicate", "distillation", table_param="source_csv",
       inputs=[_csv_in("source_csv"), _col_in("subset_column", "Dedup on", ANY)],
       output=_out_csv("output_csv", "Deduplicated_Output"), projects="passthrough"),
    _n("top_n_by_column", "Top N By Column", "distillation", table_param="source_csv",
       inputs=[_csv_in("source_csv"), _col_in("sort_column", "Sort by", ["number", "date"])],
       prefs=[_pref("n", "N", "number", 100), _pref("ascending", "Ascending", "checkbox", False)],
       output=_out_csv("output_csv", "Top_N_Output"), projects="passthrough"),
    _n("select_columns", "Select Columns", "distillation", table_param="source_csv",
       inputs=[_csv_in("source_csv")],
       prefs=[_pref("columns", "Columns (comma-sep)", "text", ""),
              _pref("drop", "Drop instead of keep", "checkbox", False)],
       output=_out_csv("output_csv", "Selected_Columns_Output"), projects="passthrough"),
    _n("arithmetic", "Arithmetic", "distillation", table_param="source_csv",
       inputs=[_csv_in("source_csv"), _col_in("column_a", "Column A", ["number"])],
       prefs=[_pref("operation", "Operation", "select", "divide", ["add", "subtract", "multiply", "divide"]),
              _pref("operand", "Operand (column or number)", "text", ""),
              _pref("new_column_name", "New column", "text", "result"),
              _pref("group_by", "Group by (optional)", "text", "")],
       output=_out_csv("output_csv", "Arithmetic_Output"), projects="arithmetic"),
    _n("group_aggregate", "Group Aggregate", "distillation", table_param="source_csv",
       inputs=[_csv_in("source_csv"), _col_in("group_column", "Group by", CATEGORICAL),
               _col_in("value_column", "Value", ["number"], optional=True)],
       prefs=[_pref("agg", "Aggregation", "select", "count", ["count", "mean", "sum", "min", "max"]),
              _pref("exclude", "Exclude values", "text", "")],
       output=_out_csv("output_csv", "Grouped_Output"), projects="group_aggregate"),
    _n("cross_tab", "Cross Tab", "distillation", table_param="source_csv",
       inputs=[_csv_in("source_csv"), _col_in("row_column", "Rows", CATEGORICAL),
               _col_in("column_column", "Columns", CATEGORICAL)],
       output=_out_csv("output_csv", "Cross_Tab_Output"), projects="replace"),
    _n("aggregate_dictionary", "Aggregate Dictionary", "distillation", table_param="source_csv",
       inputs=[_csv_in("source_csv"), _col_in("dict_column", "Dict column", ["text"])],
       output=_out_csv("output_csv", "Aggregated_Counts"), projects="replace"),
    _n("combine_csvs", "Combine CSVs", "distillation", table_param=None,
       inputs=[_csv_in("__csv_a__", "CSV A"), _csv_in("__csv_b__", "CSV B")],
       prefs=[_pref("source_column", "Source tag column", "text", "source")],
       output=_out_csv("output_csv", "Combined_Corpus"), projects="replace"),
]

# ---- Visualization nodes: column input(s) -> HTML (terminal) ----
VISUALIZATION_NODES = [
    _n("bar_chart", "Bar Chart", "visualization", table_param="csv_name",
       inputs=[_col_in("category_column", "Category", CATEGORICAL),
               _col_in("value_column", "Value", ["number"], optional=True),
               _col_in("series_column", "Series", CATEGORICAL, optional=True)],
       prefs=[_pref("chart_title", "Title", "text", ""), _pref("top_n", "Top N", "number", 25),
              _pref("exclude", "Exclude values", "text", "")],
       output=_out_html("output_name", "bar_chart")),
    _n("histogram", "Histogram", "visualization", table_param="csv_name",
       inputs=[_col_in("value_column", "Value", ["number", "date"]),
               _col_in("color_column", "Color", CATEGORICAL, optional=True)],
       prefs=[_pref("bins", "Bins", "number", 30), _pref("chart_title", "Title", "text", ""),
              _pref("log_x", "Log X", "checkbox", False), _pref("log_y", "Log Y", "checkbox", False)],
       output=_out_html("output_name", "histogram")),
    _n("scatter_plot", "Scatter Plot", "visualization", table_param="csv_name",
       inputs=[_col_in("x_column", "X", AXIS, optional=True), _col_in("y_column", "Y", AXIS, optional=True),
               _col_in("color_column", "Color", CATEGORICAL, optional=True),
               _col_in("size_column", "Size", ["number"], optional=True),
               _col_in("coord_column", "Coord (2d embedding)", ["embedding"], optional=True)],
       prefs=[_pref("chart_title", "Title", "text", "")],
       output=_out_html("output_name", "scatter")),
    _n("line_chart", "Line Chart", "visualization", table_param="csv_name",
       inputs=[_col_in("x_column", "X", AXIS), _col_in("y_column", "Y", ["number"]),
               _col_in("color_column", "Color", CATEGORICAL, optional=True)],
       prefs=[_pref("chart_title", "Title", "text", "")],
       output=_out_html("output_name", "line_chart")),
    _n("box_plot", "Box Plot", "visualization", table_param="csv_name",
       inputs=[_col_in("value_column", "Value", ["number"]),
               _col_in("category_column", "Category", CATEGORICAL, optional=True)],
       prefs=[_pref("chart_title", "Title", "text", ""), _pref("exclude", "Exclude values", "text", ""),
              _pref("log_y", "Log Y", "checkbox", False)],
       output=_out_html("output_name", "box_plot")),
    _n("heatmap", "Heatmap", "visualization", table_param="csv_name",
       inputs=[_col_in("x_column", "X", CATEGORICAL), _col_in("y_column", "Y", CATEGORICAL),
               _col_in("value_column", "Value", ["number"])],
       prefs=[_pref("chart_title", "Title", "text", "")],
       output=_out_html("output_name", "heatmap")),
    _n("pie_chart", "Pie Chart", "visualization", table_param="csv_name",
       inputs=[_col_in("category_column", "Category", CATEGORICAL),
               _col_in("value_column", "Value", ["number"], optional=True)],
       prefs=[_pref("chart_title", "Title", "text", ""), _pref("top_n", "Top N", "number", 10),
              _pref("exclude", "Exclude values", "text", "")],
       output=_out_html("output_name", "pie_chart")),
    _n("distance_map", "Distance Map", "visualization", table_param="csv_name",
       inputs=[_col_in("topic_column", "Topic id", ["number", "text"]),
               _col_in("text_column", "Text", ["text"]),
               _col_in("embedding_column", "2d coord", ["embedding"])],
       prefs=[_pref("chart_title", "Title", "text", "")],
       output=_out_html("output_name", "Topics")),
]

ALL_NODES = SOURCE_NODES + ANNOTATION_NODES + DISTILLATION_NODES + VISUALIZATION_NODES
MANIFEST = {node["action"]: node for node in ALL_NODES}

PALETTE = [
    {"category": "source", "label": "Inputs", "nodes": [n["action"] for n in SOURCE_NODES]},
    {"category": "annotation", "label": "Annotation", "nodes": [n["action"] for n in ANNOTATION_NODES]},
    {"category": "distillation", "label": "Distillation", "nodes": [n["action"] for n in DISTILLATION_NODES]},
    {"category": "visualization", "label": "Visualization", "nodes": [n["action"] for n in VISUALIZATION_NODES]},
]


def manifest_json() -> str:
    return json.dumps({"nodes": MANIFEST, "palette": PALETTE})
