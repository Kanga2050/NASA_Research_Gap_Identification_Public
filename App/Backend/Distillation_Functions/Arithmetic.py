from pathlib import Path

import numpy as np
import pandas as pd

OPERATIONS = {
    "add": lambda a, b: a + b,
    "subtract": lambda a, b: a - b,
    "multiply": lambda a, b: a * b,
    "divide": lambda a, b: a / b,
}


def arithmetic(source_csv: str, output_csv: str, column_a: str, operation: str, operand, new_column: str = "result", group_by: str = "", csv_root: str | Path | None = None):
    """Basic column arithmetic: write `new_column = column_a <operation> operand` to a
    new CSV. `operation` is add/subtract/multiply/divide. `operand` is either another
    column name or a numeric constant (auto-detected). When `group_by` is given and
    `operand` is a column, the operand is replaced by its per-group SUM (broadcast to
    every row) -- so e.g. count / sum(count) within each group yields each row's share
    of its group, which times 100 is a percentage."""
    source_path = Path(csv_root) / f"{source_csv}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{source_csv}.csv")
    output_path = Path(csv_root) / f"{output_csv}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{output_csv}.csv")

    op = (operation or "").lower()
    if op not in OPERATIONS:
        raise ValueError(f"Unsupported operation '{operation}'. Choose one of {sorted(OPERATIONS)}.")

    print(f"Computing '{new_column}' = {column_a} {op} {operand}" + (f" (per {group_by} group)" if group_by else "") + "...")
    df = pd.read_csv(source_path)
    if column_a not in df.columns:
        raise ValueError(f"Column '{column_a}' was not found in the source dataset.")

    left = pd.to_numeric(df[column_a], errors="coerce")

    operand_text = str(operand).strip()
    if operand_text in df.columns:
        right = pd.to_numeric(df[operand_text], errors="coerce")
        if group_by:
            if group_by not in df.columns:
                raise ValueError(f"group_by column '{group_by}' was not found in the source dataset.")
            right = right.groupby(df[group_by]).transform("sum")
    else:
        try:
            right = float(operand_text)
        except ValueError:
            raise ValueError(f"Operand '{operand}' is neither a column in the dataset nor a number.")

    result = OPERATIONS[op](left, right)
    if isinstance(result, pd.Series):
        result = result.replace([np.inf, -np.inf], np.nan)

    df[new_column] = result
    df.to_csv(output_path, index=False)
    print(f"Success! Wrote column '{new_column}' into '{output_csv}'.")


if __name__ == "__main__":
    # Each (topic, year) count as a percentage of its topic's total papers.
    arithmetic(
        source_csv="Topic_Year_Counts",
        output_csv="Topic_Year_Fraction",
        column_a="count",
        operation="divide",
        operand="count",
        new_column="percent",
        group_by="Topic_Label",
    )
