import json
from collections import Counter
from pathlib import Path

import pandas as pd

from Backend.backend_utils import atomic_write_csv
from Backend.nlp_utils import MAX_TEXT_CHARS, NLP, lemmas
from Servers.storage_paths import resolve_csv_path


def word_frequency(csv_name: str, text_column: str, new_column_name: str = "word_freq", ngram: int = 1, csv_root: str | Path | None = None):
    """Annotate each row with its own word-frequency dictionary, stored (as JSON)
    in `new_column_name`. Words are lowercased, lemmatized and stop-word filtered;
    set `ngram` to 2 or 3 to count underscore-joined phrases instead of single
    words. Feed the resulting column to `aggregate_dictionary` to roll many rows up
    into one corpus-wide [key, sum] table for charting."""
    csv_path = resolve_csv_path(csv_name, csv_root)

    print(f"Loading data from '{csv_path}'...")
    df = pd.read_csv(csv_path)

    if text_column not in df.columns:
        raise ValueError(f"Column '{text_column}' was not found in the CSV.")

    ngram = max(1, int(ngram))
    texts = df[text_column].fillna("").astype(str).str.slice(0, MAX_TEXT_CHARS).tolist()

    print(f"Counting per-row word frequencies (ngram={ngram}) across {len(texts)} rows...")
    frequencies = []
    for doc in NLP.pipe(texts, batch_size=64):
        tokens = lemmas(doc)
        if ngram > 1:
            tokens = ["_".join(tokens[i:i + ngram]) for i in range(len(tokens) - ngram + 1)]
        frequencies.append(json.dumps(dict(Counter(tokens))))

    df[new_column_name] = frequencies

    print(f"Writing updated dataset safely to '{csv_path}'...")
    atomic_write_csv(df, csv_path)
    print(f"Success! Per-row word frequencies saved to column '{new_column_name}'.")


if __name__ == "__main__":
    word_frequency(
        csv_name="Topic_1",
        text_column="abstract",
        new_column_name="word_freq",
        ngram=1,
    )
