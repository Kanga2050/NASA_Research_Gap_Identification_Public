import json
import os
from collections import Counter
from pathlib import Path

import pandas as pd
import spacy

# Reuse the same lightweight spaCy setup Distance_Map.py uses: lemmatize and drop
# stopwords, keeping nouns/adjectives when POS tags are available.
try:
    nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])
    HAS_POS_TAGS = True
except OSError:
    nlp = spacy.blank("en")
    HAS_POS_TAGS = False

MAX_TEXT_CHARS = 100000


def _lemmas(doc):
    if HAS_POS_TAGS:
        return [
            (token.lemma_ or token.text).lower() for token in doc
            if token.is_alpha and not token.is_stop and token.pos_ in ("NOUN", "ADJ")
        ]
    return [
        (token.lemma_ or token.text).lower() for token in doc
        if token.is_alpha and not token.is_stop
    ]


def word_frequency(csv_name: str, text_column: str, new_column_name: str = "word_freq", ngram: int = 1, csv_root: str | Path | None = None):
    """Annotate each row with its own word-frequency dictionary, stored (as JSON)
    in `new_column_name`. Words are lowercased, lemmatized and stop-word filtered;
    set `ngram` to 2 or 3 to count underscore-joined phrases instead of single
    words. Feed the resulting column to `aggregate_dictionary` to roll many rows up
    into one corpus-wide [key, sum] table for charting."""
    csv_path = Path(csv_root) / f"{csv_name}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{csv_name}.csv")

    print(f"Loading data from '{csv_path}'...")
    df = pd.read_csv(csv_path)

    if text_column not in df.columns:
        raise ValueError(f"Column '{text_column}' was not found in the CSV.")

    ngram = max(1, int(ngram))
    texts = df[text_column].fillna("").astype(str).str.slice(0, MAX_TEXT_CHARS).tolist()

    print(f"Counting per-row word frequencies (ngram={ngram}) across {len(texts)} rows...")
    frequencies = []
    for doc in nlp.pipe(texts, batch_size=64):
        tokens = _lemmas(doc)
        if ngram > 1:
            tokens = ["_".join(tokens[i:i + ngram]) for i in range(len(tokens) - ngram + 1)]
        frequencies.append(json.dumps(dict(Counter(tokens))))

    df[new_column_name] = frequencies

    print(f"Writing updated dataset safely to '{csv_path}'...")
    temp_path = Path(str(csv_path) + ".tmp")
    df.to_csv(temp_path, index=False)
    os.replace(temp_path, csv_path)
    print(f"Success! Per-row word frequencies saved to column '{new_column_name}'.")


if __name__ == "__main__":
    word_frequency(
        csv_name="Topic_1",
        text_column="abstract",
        new_column_name="word_freq",
        ngram=1,
    )
