"""Distillation functions: read one or more CSVs and write a NEW, derived CSV.

Unlike the annotation family (which edits its source in place), every function here
leaves its input untouched and produces a fresh table -- a filtered subset, a summary,
a reshaped matrix. That new table is what the Studio wires onward as a csv output.
"""
from __future__ import annotations

import ast
import json
import warnings
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from .backend_utils import ProgressReporter, as_bool, drop_excluded, load_csv, require_columns, save_csv

ALLOWED_AGGS = {"count", "mean", "sum", "min", "max"}

OPERATIONS = {
    "add": lambda a, b: a + b,
    "subtract": lambda a, b: a - b,
    "multiply": lambda a, b: a * b,
    "divide": lambda a, b: a / b,
}


def numerical_filter(
    source_csv: str,
    output_csv: str,
    target_score_column: str,
    threshold: float,
    csv_root: str | Path | None = None,
):
    """Keep only rows whose `target_score_column` is >= `threshold`, writing them
    (sorted best-first) to a new CSV. Works on numeric columns and on ISO-8601 date
    columns, where a date threshold like "2015-01-01" filters chronologically."""
    print(f"Loading '{source_csv}.csv' to filter rows where '{target_score_column}' >= {threshold}...")
    df = load_csv(source_csv, csv_root, columns=(target_score_column,))

    print(f"Applying threshold to {len(df):,} rows...")
    column = df[target_score_column]

    # Prefer a numeric comparison when both the column and the threshold are numeric:
    # numbers spuriously "parse" as dates via epoch offsets, so numeric must win.
    # Otherwise treat it as a date column -- to_date stores monotonic ISO-8601 strings,
    # which (like numbers) already sort correctly on the raw column.
    col_numeric = pd.to_numeric(column, errors="coerce")
    threshold_numeric = pd.to_numeric(pd.Series([threshold]), errors="coerce").iloc[0]
    if pd.notna(threshold_numeric) and col_numeric.notna().mean() >= 0.8:
        mask = col_numeric >= threshold_numeric
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            mask = pd.to_datetime(column, errors="coerce") >= pd.to_datetime(threshold)

    result = df[mask.fillna(False)].sort_values(by=target_score_column, ascending=False)

    save_csv(result, output_csv, csv_root)
    kept = len(result)
    print(f"Success! Kept {kept:,} of {len(df):,} rows ({kept / max(len(df), 1) * 100:.1f}%) "
          f"meeting '{target_score_column}' >= {threshold} → new file '{output_csv}.csv'.")


def categorical_filter(
    source_csv: str,
    output_csv: str,
    target_column: str,
    expected_value,
    csv_root: str | Path | None = None,
):
    """Keep only the rows whose `target_column` exactly equals `expected_value`.
    Compared as text, so a value the user typed (e.g. topic id "1") matches whatever
    the column's dtype happens to be."""
    print(f"Loading '{source_csv}.csv' to keep rows where {target_column} == {expected_value!r}...")
    df = load_csv(source_csv, csv_root, columns=(target_column,))

    print(f"Scanning {len(df):,} rows for exact matches...")
    matched = df[df[target_column].astype(str) == str(expected_value)]

    save_csv(matched, output_csv, csv_root)
    print(f"Success! Extracted {len(matched):,} of {len(df):,} rows where {target_column} == "
          f"{expected_value!r} → new file '{output_csv}.csv'.")


def combine_csvs(
    source_csvs: str,
    output_csv: str,
    source_column: str = "source",
    csv_root: str | Path | None = None,
):
    """Stack several CSVs into one (outer-union of columns), adding `source_column`
    tagging every row with the name of the CSV it came from. `source_csvs` is a
    comma-separated list of names, e.g. "Microgravity,Space_Crops"."""
    names = [name.strip() for name in str(source_csvs).split(",") if name.strip()]
    if len(names) < 2:
        raise ValueError("Provide at least two comma-separated CSV names to combine.")

    frames = []
    total_rows = 0
    for i, name in enumerate(names, start=1):
        part = load_csv(name, csv_root)
        part[source_column] = name
        frames.append(part)
        total_rows += len(part)
        print(f"Loaded {i}/{len(names)}: '{name}' ({len(part):,} rows, {total_rows:,} rows stacked so far)...")

    print(f"Concatenating {len(names)} files (outer-union of columns) and writing '{output_csv}.csv'...")
    combined = pd.concat(frames, ignore_index=True, sort=False)

    save_csv(combined, output_csv, csv_root)
    print(f"Success! Stacked {len(names)} files into '{output_csv}.csv' ({len(combined):,} rows), "
          f"origin tagged in column '{source_column}'.")


def _parse_dict(cell):
    """Parse one stored {key: number} cell, written either as JSON (word_frequency)
    or as a Python repr (an older column, or a hand-edited CSV)."""
    if isinstance(cell, dict):
        return cell
    text = str(cell)
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return None
    return parsed if isinstance(parsed, dict) else None


def aggregate_dictionary(
    source_csv: str,
    output_csv: str,
    dict_column: str,
    csv_root: str | Path | None = None,
):
    """Sum the per-row {key: number} dictionaries stored in `dict_column` across every
    row, producing a new two-column [key, sum] CSV sorted by descending total. Pairs
    with `word_frequency` to build a corpus-wide frequency table ready for a bar chart."""
    print(f"Loading '{source_csv}.csv' to sum the per-row dictionaries in column '{dict_column}'...")
    df = load_csv(source_csv, csv_root, columns=(dict_column,))

    cells = df[dict_column].dropna()
    reporter = ProgressReporter(f"Summing {len(cells):,} dictionaries", len(cells))
    totals: Counter = Counter()
    for i, cell in enumerate(cells, start=1):
        reporter.update(i)
        parsed = _parse_dict(cell)
        if not parsed:
            continue
        for key, value in parsed.items():
            try:
                totals[str(key)] += float(value)
            except (TypeError, ValueError):
                continue

    result = pd.DataFrame(totals.most_common(), columns=["key", "sum"])
    # Present whole-number sums as ints rather than 1.0, 2.0, ...
    if not result.empty and (result["sum"] % 1 == 0).all():
        result["sum"] = result["sum"].astype(int)

    save_csv(result, output_csv, csv_root)
    print(f"Success! Rolled {len(cells):,} rows up into {len(result):,} distinct keys "
          f"(sorted by total) → new file '{output_csv}.csv'.")


def group_aggregate(
    source_csv: str,
    output_csv: str,
    group_column: str,
    value_column: str = "",
    agg: str = "count",
    exclude: str = "",
    csv_root: str | Path | None = None,
):
    """Group rows by `group_column` and aggregate them into a summary CSV. Pass a
    comma-separated `group_column` (e.g. "Topic_Label,year") to group by several
    columns at once, producing long-form multi-dimensional counts. With agg="count"
    (or no `value_column`) it counts rows per group; otherwise it applies
    mean/sum/min/max to `value_column`. `exclude` drops comma-separated values of the
    first group column before aggregating (e.g. "-1" to omit HDBSCAN noise)."""
    agg = (agg or "count").lower()
    if agg not in ALLOWED_AGGS:
        raise ValueError(f"Unsupported aggregation '{agg}'. Choose one of {sorted(ALLOWED_AGGS)}.")

    group_cols = [col.strip() for col in str(group_column).split(",") if col.strip()]
    if not group_cols:
        raise ValueError("Provide at least one column to group by.")

    op_desc = "counting rows" if (agg == "count" or not value_column) else f"taking {agg} of '{value_column}'"
    print(f"Loading '{source_csv}.csv' to group by {group_cols} ({op_desc})...")
    df = load_csv(source_csv, csv_root, columns=tuple(group_cols))

    before = len(df)
    df = drop_excluded(df, group_cols[0], exclude)
    if exclude:
        print(f"Excluded {before - len(df):,} rows via exclude='{exclude}'; aggregating {len(df):,} rows...")
    else:
        print(f"Aggregating {len(df):,} rows into groups...")

    if agg == "count" or not value_column:
        result = df.groupby(group_cols, dropna=False).size().reset_index(name="count")
        result_column = "count"
    else:
        require_columns(df, value_column)
        result_column = f"{value_column}_{agg}"
        result = df.groupby(group_cols, dropna=False)[value_column].agg(agg).reset_index(name=result_column)

    result = result.sort_values(by=result_column, ascending=False)

    save_csv(result, output_csv, csv_root)
    print(f"Success! Summarized {len(df):,} rows into {len(result):,} groups "
          f"(column '{result_column}') → new file '{output_csv}.csv'.")


def top_n_by_column(
    source_csv: str,
    output_csv: str,
    sort_column: str,
    n: int = 100,
    ascending=False,
    csv_root: str | Path | None = None,
):
    """Sort by `sort_column` and keep the top `n` rows. Unlike `numerical_filter` this
    is threshold-free -- e.g. "top 100 papers by favorability" regardless of the
    absolute score."""
    ascending = as_bool(ascending)
    n = int(n)
    order = "smallest" if ascending else "largest"
    print(f"Loading '{source_csv}.csv' to take the top {n:,} rows by {order} '{sort_column}'...")
    df = load_csv(source_csv, csv_root, columns=(sort_column,))

    print(f"Sorting {len(df):,} rows and keeping the top {n:,}...")
    result = df.sort_values(by=sort_column, ascending=ascending).head(n)

    save_csv(result, output_csv, csv_root)
    print(f"Success! Kept the top {len(result):,} of {len(df):,} rows by '{sort_column}' "
          f"({order} first) → new file '{output_csv}.csv'.")


def deduplicate(
    source_csv: str,
    output_csv: str,
    subset_column: str,
    csv_root: str | Path | None = None,
):
    """Drop rows that repeat a value in `subset_column`, keeping the first occurrence
    -- e.g. dedupe papers by title or doi."""
    print(f"Loading '{source_csv}.csv' to drop rows repeating a value in '{subset_column}'...")
    df = load_csv(source_csv, csv_root, columns=(subset_column,))

    before = len(df)
    print(f"Scanning {before:,} rows for duplicate '{subset_column}' values (keeping the first of each)...")
    result = df.drop_duplicates(subset=[subset_column])

    save_csv(result, output_csv, csv_root)
    print(f"Success! Removed {before - len(result):,} duplicate rows; {len(result):,} unique rows "
          f"remain → new file '{output_csv}.csv'.")


def select_columns(
    source_csv: str,
    output_csv: str,
    columns: str,
    drop=False,
    csv_root: str | Path | None = None,
):
    """Write a new CSV keeping only `columns` (comma-separated), or -- with `drop` --
    keeping everything EXCEPT those columns. Handy for stripping a heavy embedding
    column before export, or slimming a table down to what a chart needs."""
    wanted = [col.strip() for col in str(columns).split(",") if col.strip()]
    if not wanted:
        raise ValueError("Provide at least one column name.")

    drop_mode = as_bool(drop)
    print(f"Loading '{source_csv}.csv' to {'drop' if drop_mode else 'keep only'} columns {wanted}...")
    df = load_csv(source_csv, csv_root, columns=tuple(wanted))

    result = df.drop(columns=wanted) if drop_mode else df[wanted]
    print(f"Reshaping {len(df):,} rows from {len(df.columns)} → {len(result.columns)} columns...")

    save_csv(result, output_csv, csv_root)
    print(f"Success! Wrote {len(result.columns)} columns × {len(result):,} rows → new file '{output_csv}.csv'.")


def cross_tab(
    source_csv: str,
    output_csv: str,
    row_column: str,
    column_column: str,
    csv_root: str | Path | None = None,
):
    """Build a contingency table counting how many rows fall into each
    (`row_column`, `column_column`) pairing. The output has `row_column` as its first
    column and one numeric column per distinct `column_column` value -- the matrix
    form a `heatmap` expects."""
    print(f"Loading '{source_csv}.csv' to cross-tabulate '{row_column}' (rows) against '{column_column}' (columns)...")
    df = load_csv(source_csv, csv_root, columns=(row_column, column_column))

    print(f"Counting {len(df):,} rows into a contingency matrix...")
    table = pd.crosstab(df[row_column], df[column_column])

    save_csv(table.reset_index(), output_csv, csv_root)
    print(f"Success! Wrote a {table.shape[0]}×{table.shape[1]} count matrix "
          f"('{row_column}' vs '{column_column}') → new file '{output_csv}.csv'.")


def arithmetic(
    source_csv: str,
    output_csv: str,
    column_a: str,
    operation: str,
    operand,
    new_column: str = "result",
    group_by: str = "",
    csv_root: str | Path | None = None,
):
    """Column arithmetic: write `new_column = column_a <operation> operand` to a new
    CSV. `operand` is either another column name or a numeric constant (auto-detected).
    When `group_by` is given and `operand` is a column, the operand is replaced by its
    per-group SUM broadcast to every row -- so count / sum(count) within each group
    yields each row's share of its group, which times 100 is a percentage."""
    op = (operation or "").lower()
    if op not in OPERATIONS:
        raise ValueError(f"Unsupported operation '{operation}'. Choose one of {sorted(OPERATIONS)}.")

    grouped = f" (operand summed per '{group_by}' group)" if group_by else ""
    print(f"Loading '{source_csv}.csv' to compute '{new_column}' = {column_a} {op} {operand}{grouped}...")
    df = load_csv(source_csv, csv_root, columns=(column_a,))

    print(f"Applying the {op} across {len(df):,} rows...")
    left = pd.to_numeric(df[column_a], errors="coerce")

    operand_text = str(operand).strip()
    if operand_text in df.columns:
        right = pd.to_numeric(df[operand_text], errors="coerce")
        if group_by:
            require_columns(df, group_by)
            right = right.groupby(df[group_by]).transform("sum")
    else:
        try:
            right = float(operand_text)
        except ValueError:
            raise ValueError(f"Operand '{operand}' is neither a column in the dataset nor a number.") from None

    result = OPERATIONS[op](left, right)
    if isinstance(result, pd.Series):
        result = result.replace([np.inf, -np.inf], np.nan)
    df[new_column] = result

    save_csv(df, output_csv, csv_root)
    print(f"Success! Computed '{new_column}' = {column_a} {op} {operand} for {len(df):,} rows "
          f"→ new file '{output_csv}.csv'.")
