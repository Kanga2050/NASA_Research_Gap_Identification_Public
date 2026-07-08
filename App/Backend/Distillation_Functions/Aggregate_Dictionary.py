import ast
import json
from collections import Counter
from pathlib import Path

import pandas as pd


def _parse_dict(cell):
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


def aggregate_dictionary(source_csv: str, output_csv: str, dict_column: str, csv_root: str | Path | None = None):
    """Sum the per-row `{key: number}` dictionaries stored (stringified) in
    `dict_column` across every row, producing a new two-column CSV [key, sum],
    sorted by descending sum. Pairs with `word_frequency` to build a corpus-wide
    frequency table ready for a bar chart."""
    source_path = Path(csv_root) / f"{source_csv}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{source_csv}.csv")
    output_path = Path(csv_root) / f"{output_csv}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{output_csv}.csv")

    print(f"Aggregating dictionaries from column '{dict_column}' in '{source_csv}'...")
    df = pd.read_csv(source_path)

    if dict_column not in df.columns:
        raise ValueError(f"Column '{dict_column}' was not found in the source dataset.")

    totals: Counter = Counter()
    for cell in df[dict_column].dropna():
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

    result.to_csv(output_path, index=False)
    print(f"Success! Aggregated {len(result)} distinct keys into '{output_csv}'.")


if __name__ == "__main__":
    aggregate_dictionary(
        source_csv="Topic_1",
        output_csv="Topic_1_Word_Counts",
        dict_column="word_freq",
    )
