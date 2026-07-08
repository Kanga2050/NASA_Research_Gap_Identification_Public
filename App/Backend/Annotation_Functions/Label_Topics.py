import os
from collections import Counter
from pathlib import Path

import pandas as pd
import spacy

# Same lightweight spaCy setup Distance_Map.py / Word_Frequency.py use: lemmatize
# and drop stopwords, keeping nouns/adjectives when POS tags are available.
try:
    nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])
    HAS_POS_TAGS = True
except OSError:
    nlp = spacy.blank("en")
    HAS_POS_TAGS = False

MAX_TEXT_CHARS = 100000


def _topic_keywords(texts, top_n):
    """Return the top_n keywords (comma-joined) describing a topic's pooled text --
    the same keyword logic Distance_Map.get_topic_names uses."""
    doc = nlp(" ".join(texts)[:MAX_TEXT_CHARS])
    if HAS_POS_TAGS:
        words = [
            (token.lemma_ or token.text).lower() for token in doc
            if token.is_alpha and not token.is_stop and token.pos_ in ("NOUN", "ADJ")
        ]
    else:
        words = [
            (token.lemma_ or token.text).lower() for token in doc
            if token.is_alpha and not token.is_stop
        ]
    return ", ".join(word for word, _ in Counter(words).most_common(top_n))


def label_topics(csv_name: str, topic_column: str = "topic_id", text_column: str = "abstract", new_column_name: str = "Topic_Label", top_n: int = 3, csv_root: str | Path | None = None):
    """Annotate each row with a human-readable topic label (its top keywords) built
    from the pooled text of its topic -- the labels the Distance Map shows, but
    written into a `new_column_name` column so any chart can group by it instead of
    the raw topic number. The HDBSCAN noise cluster (-1) is left as its own value so
    charts can still `exclude` it. Builds a {topic: label} dictionary and maps it
    onto the topic column."""
    csv_path = Path(csv_root) / f"{csv_name}.csv" if csv_root is not None else Path(f"App/Backend/CSVs/{csv_name}.csv")

    print(f"Loading data from '{csv_path}'...")
    df = pd.read_csv(csv_path)
    for column in (topic_column, text_column):
        if column not in df.columns:
            raise ValueError(f"Column '{column}' was not found in the CSV.")

    topics = [topic for topic in df[topic_column].dropna().unique() if topic != -1]
    print(f"Generating keyword labels for {len(topics)} topics...")
    labels = {}
    for topic in topics:
        topic_texts = df.loc[df[topic_column] == topic, text_column].fillna("").tolist()
        labels[topic] = _topic_keywords(topic_texts, int(top_n))

    # Dictionary lookup: map each row's topic to its label; unlabelled rows (noise,
    # or a topic with no keywords) fall back to the topic value as text.
    df[new_column_name] = df[topic_column].map(labels).fillna(df[topic_column].astype(str))

    print(f"Writing updated dataset safely to '{csv_path}'...")
    temp_path = Path(f"{csv_path}.tmp")
    df.to_csv(temp_path, index=False)
    os.replace(temp_path, csv_path)
    print(f"Success! Topic labels saved to column '{new_column_name}'.")


if __name__ == "__main__":
    label_topics(
        csv_name="Space_Biology",
        topic_column="topic_id",
        text_column="abstract",
        new_column_name="Topic_Label",
        top_n=3,
    )
