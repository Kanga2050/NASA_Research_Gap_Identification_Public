from pathlib import Path

import pandas as pd

from Backend.backend_utils import atomic_write_csv
from Backend.nlp_utils import top_keywords
from Servers.storage_paths import resolve_csv_path


def label_topics(csv_name: str, topic_column: str = "topic_id", text_column: str = "abstract", new_column_name: str = "Topic_Label", top_n: int = 3, csv_root: str | Path | None = None):
    """Annotate each row with a human-readable topic label (its top keywords) built
    from the pooled text of its topic -- the labels the Distance Map shows, but
    written into a `new_column_name` column so any chart can group by it instead of
    the raw topic number. The HDBSCAN noise cluster (-1) is left as its own value so
    charts can still `exclude` it. Builds a {topic: label} dictionary and maps it
    onto the topic column."""
    csv_path = resolve_csv_path(csv_name, csv_root)

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
        labels[topic] = top_keywords(topic_texts, int(top_n))

    # Dictionary lookup: map each row's topic to its label; unlabelled rows (noise,
    # or a topic with no keywords) fall back to the topic value as text.
    df[new_column_name] = df[topic_column].map(labels).fillna(df[topic_column].astype(str))

    print(f"Writing updated dataset safely to '{csv_path}'...")
    atomic_write_csv(df, csv_path)
    print(f"Success! Topic labels saved to column '{new_column_name}'.")


if __name__ == "__main__":
    label_topics(
        csv_name="Space_Biology",
        topic_column="topic_id",
        text_column="abstract",
        new_column_name="Topic_Label",
        top_n=3,
    )
