"""Annotation functions: add a column to a CSV, in place.

Every function here reads one CSV, computes a new column from an existing one, and
writes the same CSV back (atomically). They are the building blocks of the retrieval
pipeline: embed -> reduce -> cluster -> label, plus the scoring family.

The heavy ML dependencies (sentence-transformers/torch, UMAP, HDBSCAN, scikit-learn,
spaCy) are imported INSIDE the functions that need them, not at module scope. The task
engine imports this module to run any annotation, so a top-level import would make a
two-second `text_length` job pay a ~20-second model-stack import it never uses.
"""
from __future__ import annotations

import json
import os
import warnings
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from .backend_utils import (
    ProgressReporter,
    cosine_similarity_dense,
    load_csv,
    require_columns,
    save_csv,
    stacked_vectors,
)
from App.Servers.storage_paths import resolve_csv_path


def embed_text(
    csv_name: str,
    text_column: str,
    new_column_name: str,
    model_name: str = "allenai/specter2_base",
    chunk_size: int = 5000,
    batch_size: int = 32,
    csv_root: str | Path | None = None,
):
    """Compute a semantic embedding vector for each row's `text_column` and store it
    (stringified) in `new_column_name`, editing the CSV in place. The foundation for
    semantic search, dimensionality reduction and clustering.

    The CSV is streamed in chunks so a corpus larger than memory can still be embedded.
    """
    from sentence_transformers import SentenceTransformer

    csv_path = resolve_csv_path(csv_name, csv_root)
    if not Path(csv_path).exists():
        raise ValueError(f"No CSV named '{csv_name}' in this workspace.")

    print(f"Loading embedding model '{model_name}' (first run downloads weights, this can take ~30s)...")
    model = SentenceTransformer(model_name)
    print(f"Model ready. Streaming '{csv_name}.csv' in chunks of {chunk_size:,} rows to embed column '{text_column}'.")

    temp_path = Path(f"{csv_path}.tmp")
    temp_path.unlink(missing_ok=True)

    first_chunk = True
    rows_done = 0
    for chunk_index, chunk in enumerate(pd.read_csv(csv_path, chunksize=chunk_size)):
        if text_column not in chunk.columns:
            temp_path.unlink(missing_ok=True)
            require_columns(chunk, text_column)
        texts = chunk[text_column].fillna("").astype(str).tolist()

        # Encode batch-by-batch (rather than one big call) so the progress bar can
        # advance within the chunk -- model.encode's own bar goes to stderr and never
        # reaches the frontend.
        reporter = ProgressReporter(f"Embedding rows (chunk {chunk_index + 1})", len(texts))
        embeddings = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            embeddings.extend(model.encode(batch, batch_size=batch_size, show_progress_bar=False).tolist())
            reporter.update(start + len(batch))

        chunk[new_column_name] = embeddings
        chunk.to_csv(temp_path, mode="w" if first_chunk else "a", header=first_chunk, index=False)
        first_chunk = False
        rows_done += len(texts)
        print(f"Chunk {chunk_index + 1} embedded and buffered ({rows_done:,} rows done so far).")

    print("Committing embeddings to disk (atomic replace)...")
    os.replace(temp_path, csv_path)
    print(f"Success! Embedded {rows_done:,} rows of '{text_column}' into new column '{new_column_name}' in '{csv_name}.csv'.")


def reduce_dimensionality(
    csv_name: str,
    embedding_column: str,
    new_column_name: str,
    n_components: int = 2,
    metric: str = "cosine",
    csv_root: str | Path | None = None,
):
    """Run UMAP to compress the embeddings in `embedding_column` down to
    `n_components` dimensions, written to `new_column_name` as stringified
    coordinates. Use n=2 for a plottable map, or n=5 as the input to clustering."""
    import umap

    df = load_csv(csv_name, csv_root, columns=(embedding_column,))

    valid_rows = df[embedding_column].dropna().index
    print(f"Parsing {len(valid_rows):,} stored embeddings into numeric vectors...")
    matrix = stacked_vectors(df.loc[valid_rows, embedding_column])

    n_components = int(n_components)
    print(f"Fitting UMAP on a {matrix.shape[0]:,}×{matrix.shape[1]} matrix → {n_components}D using '{metric}' distance.")
    print("This is the slow step (a single dense optimization, no incremental progress); please wait...")
    reducer = umap.UMAP(n_components=n_components, metric=metric, n_neighbors=15, min_dist=0.1, random_state=42)
    reduced = reducer.fit_transform(matrix)

    print(f"UMAP done. Writing {n_components}D coordinates back into column '{new_column_name}'...")
    df[new_column_name] = None
    df.loc[valid_rows, new_column_name] = pd.Series(reduced.tolist(), index=valid_rows)

    save_csv(df, csv_name, csv_root)
    print(f"Success! Reduced {len(valid_rows):,} embeddings to {n_components}D in new column '{new_column_name}' of '{csv_name}.csv'.")


def cluster(
    csv_name: str,
    embedding_column: str,
    new_column_name: str | None = None,
    min_cluster_size: int = 50,
    min_samples: int = 10,
    csv_root: str | Path | None = None,
):
    """Group rows into topics with HDBSCAN over the coordinates in `embedding_column`
    (e.g. the 5D UMAP column), writing a topic id per row into `new_column_name`.
    Larger min_cluster_size/min_samples yield fewer, tighter topics; id -1 is noise."""
    import hdbscan

    new_column_name = new_column_name or f"{embedding_column}_topic"
    df = load_csv(csv_name, csv_root, columns=(embedding_column,))

    valid_rows = df[embedding_column].dropna().index
    print(f"Parsing {len(valid_rows):,} coordinate vectors from '{embedding_column}'...")
    if len(valid_rows) < 2:
        raise ValueError(f"Column '{embedding_column}' has {len(valid_rows)} non-null row(s); need at least 2 to cluster.")
    matrix = stacked_vectors(df.loc[valid_rows, embedding_column])

    min_cluster_size, min_samples = int(min_cluster_size), int(min_samples)
    if min_cluster_size > matrix.shape[0]:
        raise ValueError(
            f"min_cluster_size ({min_cluster_size}) exceeds the {matrix.shape[0]:,} available rows; "
            "lower min_cluster_size or provide more data."
        )
    print(f"Running HDBSCAN on {matrix.shape[0]:,} points (min_cluster_size={min_cluster_size}, min_samples={min_samples})...")
    print("Density clustering runs as one pass with no incremental progress; please wait...")
    clusterer = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size, min_samples=min_samples, metric="euclidean")
    labels = clusterer.fit_predict(matrix)

    n_topics = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise = int((labels == -1).sum())
    print(f"Found {n_topics} distinct topics; {n_noise:,} points ({n_noise / max(len(labels), 1) * 100:.1f}%) fell into noise (-1).")

    df[new_column_name] = None
    df.loc[valid_rows, new_column_name] = labels

    save_csv(df, csv_name, csv_root)
    print(f"Success! Assigned {n_topics} topic ids to column '{new_column_name}' in '{csv_name}.csv' (label -1 = noise, not a topic).")


def keyword_score(
    csv_name: str,
    query: str,
    text_column: str,
    new_column_name: str = "keyword_score",
    csv_root: str | Path | None = None,
):
    """Score every row for lexical relevance to `query` via TF-IDF cosine similarity
    over `text_column`, writing a 0-1 score into `new_column_name`. Rewards exact word
    overlap; pair with `semantic_score` + `hybrid_score` for the best retrieval."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    df = load_csv(csv_name, csv_root, columns=(text_column,))
    corpus = df[text_column].fillna("").astype(str).tolist()

    # TF-IDF vectors are sparse; sklearn's cosine_similarity works directly on sparse
    # matrices, so keep it rather than densifying for the hand-rolled numpy version.
    print(f"Building TF-IDF vocabulary over {len(corpus):,} documents...")
    vectorizer = TfidfVectorizer(stop_words="english")
    try:
        tfidf_matrix = vectorizer.fit_transform(corpus)
    except ValueError as exc:
        raise ValueError(
            f"Could not build a TF-IDF vocabulary from column '{text_column}': every row is empty "
            "or contains only English stopwords after filtering."
        ) from exc
    query_vector = vectorizer.transform([query])

    print(f"Scoring {len(corpus):,} documents by keyword (TF-IDF cosine) similarity to '{query}'...")
    df[new_column_name] = cosine_similarity(query_vector, tfidf_matrix).flatten()

    save_csv(df, csv_name, csv_root)
    print(f"Success! Keyword relevance to '{query}' saved to column '{new_column_name}' in '{csv_name}.csv'.")


def semantic_score(
    csv_name: str,
    query: str,
    embedding_column: str,
    new_column_name: str = "semantic_score",
    model_name: str = "allenai/specter2_base",
    csv_root: str | Path | None = None,
):
    """Score every row for meaning-based relevance to `query` by cosine similarity
    between the query's embedding and each row's stored `embedding_column`. Catches
    paraphrases keyword search misses (requires `embed_text` first)."""
    from sentence_transformers import SentenceTransformer

    df = load_csv(csv_name, csv_root, columns=(embedding_column,))

    print(f"Loading model '{model_name}' and embedding the query '{query}'...")
    model = SentenceTransformer(model_name)
    query_embedding = model.encode([query])

    valid_rows = df[embedding_column].dropna().index
    print(f"Parsing {len(valid_rows):,} stored embeddings and computing cosine similarity to the query...")
    matrix = stacked_vectors(df.loc[valid_rows, embedding_column])

    df[new_column_name] = 0.0
    df.loc[valid_rows, new_column_name] = cosine_similarity_dense(query_embedding, matrix).flatten()

    save_csv(df, csv_name, csv_root)
    print(f"Success! Semantic (meaning-based) relevance to '{query}' saved to column '{new_column_name}' for {len(valid_rows):,} rows.")


def hybrid_score(
    csv_name: str,
    keyword_col: str,
    semantic_col: str,
    new_column_name: str = "hybrid_score",
    k: int = 60,
    csv_root: str | Path | None = None,
):
    """Fuse a keyword-score column and a semantic-score column into one combined 0-1
    relevance score via Reciprocal Rank Fusion, balancing exact-match and
    meaning-based retrieval."""
    df = load_csv(csv_name, csv_root, columns=(keyword_col, semantic_col))

    print(f"Ranking {len(df):,} rows by each score and blending the two rankings (RRF, k={k})...")
    keyword_rank = df[keyword_col].rank(ascending=False, method="min")
    semantic_rank = df[semantic_col].rank(ascending=False, method="min")
    rrf = (1.0 / (k + keyword_rank)) + (1.0 / (k + semantic_rank))

    spread = rrf.max() - rrf.min()
    df[new_column_name] = (rrf - rrf.min()) / spread if spread else 0.0

    save_csv(df, csv_name, csv_root)
    print(f"Success! Hybrid keyword+semantic relevance (0-1) saved to column '{new_column_name}' for {len(df):,} rows.")


def word_frequency(
    csv_name: str,
    text_column: str,
    new_column_name: str = "word_freq",
    ngram: int = 1,
    csv_root: str | Path | None = None,
):
    """Annotate each row with its own {word: count} dictionary (JSON) from
    `text_column` -- lowercased, lemmatized and stop-word filtered. Set `ngram` to 2
    or 3 to count underscore-joined phrases. Feed the result to `aggregate_dictionary`
    to roll every row up into one corpus-wide [key, sum] table."""
    from .nlp_utils import MAX_TEXT_CHARS, NLP, lemmas

    df = load_csv(csv_name, csv_root, columns=(text_column,))

    ngram = max(1, int(ngram))
    texts = df[text_column].fillna("").astype(str).str.slice(0, MAX_TEXT_CHARS).tolist()

    unit = "words" if ngram == 1 else f"{ngram}-word phrases"
    reporter = ProgressReporter(f"Counting {unit} across {len(texts):,} rows", len(texts))
    frequencies = []
    for i, doc in enumerate(NLP.pipe(texts, batch_size=64), start=1):
        tokens = lemmas(doc)
        if ngram > 1:
            tokens = ["_".join(tokens[j:j + ngram]) for j in range(len(tokens) - ngram + 1)]
        frequencies.append(json.dumps(dict(Counter(tokens))))
        reporter.update(i)

    df[new_column_name] = frequencies

    save_csv(df, csv_name, csv_root)
    print(f"Success! Counted {unit} into per-row frequency dictionaries in column '{new_column_name}' for {len(texts):,} rows.")


def label_topics(
    csv_name: str,
    topic_column: str = "topic_id",
    text_column: str = "text",
    new_column_name: str = "Topic_Label",
    top_n: int = 3,
    csv_root: str | Path | None = None,
):
    """Annotate each row with a human-readable topic label -- its topic's top keywords
    -- so charts can group by a readable name instead of a raw topic number. The
    HDBSCAN noise cluster (-1) keeps its own value so charts can still `exclude` it."""
    from .nlp_utils import top_keywords

    df = load_csv(csv_name, csv_root, columns=(topic_column, text_column))

    topics = [topic for topic in df[topic_column].dropna().unique() if topic != -1]
    reporter = ProgressReporter(f"Labelling {len(topics)} topics (top {int(top_n)} keywords each)", len(topics))
    labels = {}
    for i, topic in enumerate(topics, start=1):
        topic_texts = df.loc[df[topic_column] == topic, text_column].fillna("").tolist()
        labels[topic] = top_keywords(topic_texts, int(top_n))
        reporter.update(i)

    # Map each row's topic to its label; unlabelled rows (noise, or a topic with no
    # keywords) fall back to the topic value as text.
    df[new_column_name] = df[topic_column].map(labels).fillna(df[topic_column].astype(str))

    save_csv(df, csv_name, csv_root)
    print(f"Success! Keyword labels for {len(topics)} topics saved to column '{new_column_name}' in '{csv_name}.csv'.")


def text_length(
    csv_name: str,
    text_column: str,
    new_column_name: str = "length",
    unit: str = "words",
    csv_root: str | Path | None = None,
):
    """Add a numeric column measuring the length of `text_column`: `unit="words"`
    counts whitespace-separated tokens, `unit="chars"` counts characters."""
    df = load_csv(csv_name, csv_root, columns=(text_column,))

    text = df[text_column].fillna("").astype(str)
    print(f"Counting {unit} for {len(df):,} rows...")
    df[new_column_name] = text.str.len() if unit == "chars" else text.str.split().apply(len)

    save_csv(df, csv_name, csv_root)
    print(f"Success! Measured '{text_column}' length in {unit}; saved to column '{new_column_name}' for {len(df):,} rows.")


def extract_year(
    csv_name: str,
    date_column: str,
    new_column_name: str = "year",
    csv_root: str | Path | None = None,
):
    """Parse a four-digit year out of `date_column` into a new numeric column. Tries
    full date parsing first, then falls back to the first 4-digit run for anything
    pandas cannot parse. Unlocks temporal charts (e.g. publications per year)."""
    df = load_csv(csv_name, csv_root, columns=(date_column,))

    print(f"Parsing dates for {len(df):,} rows...")
    with warnings.catch_warnings():
        # Freeform values reach this parse; dateutil's per-element fallback warns noisily.
        warnings.simplefilter("ignore")
        years = pd.to_datetime(df[date_column], errors="coerce").dt.year

    unparsed = years.isna()
    if unparsed.any():
        print(f"Salvaging {int(unparsed.sum()):,} unparseable values with a 4-digit-year fallback...")
        extracted = df.loc[unparsed, date_column].astype(str).str.extract(r"(\d{4})")[0]
        years.loc[unparsed] = pd.to_numeric(extracted, errors="coerce")

    df[new_column_name] = years.astype("Int64")

    save_csv(df, csv_name, csv_root)
    filled = int(df[new_column_name].notna().sum())
    print(f"Success! Extracted a year for {filled:,}/{len(df):,} rows into column '{new_column_name}'.")


def to_date(
    csv_name: str,
    date_column: str,
    new_column_name: str = "date",
    csv_root: str | Path | None = None,
):
    """Normalize `date_column` into a canonical ISO-8601 (YYYY-MM-DD) column.

    ISO-8601 dates are monotonic under both string and datetime comparison, so the
    result is a proper "date" type that downstream range filtering, sorting and
    time-axis charts can use directly. Values pandas cannot parse become blank.
    """
    df = load_csv(csv_name, csv_root, columns=(date_column,))

    # format="mixed" parses each value independently, so heterogeneous inputs
    # ("2015-03-01", "March 2018", "2012/06/15") all resolve; unparseable -> NaT.
    print(f"Parsing {len(df):,} mixed-format dates into canonical YYYY-MM-DD...")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(df[date_column], errors="coerce", format="mixed")

    # strftime turns NaT into the string "NaT"; blank those out so unparsed rows are
    # empty rather than junk.
    df[new_column_name] = parsed.dt.strftime("%Y-%m-%d").where(parsed.notna(), "")

    save_csv(df, csv_name, csv_root)
    filled = int(parsed.notna().sum())
    print(f"Success! Wrote sortable ISO-8601 dates for {filled:,}/{len(df):,} rows into column '{new_column_name}'.")


def normalize_column(
    csv_name: str,
    value_column: str,
    new_column_name: str = "",
    csv_root: str | Path | None = None,
):
    """Min-max scale a numeric column into the 0-1 range. A blank `new_column_name`
    (or one equal to `value_column`) overwrites the column in place; otherwise the
    scaled values land in a new column. A constant column normalizes to all-zeros."""
    df = load_csv(csv_name, csv_root, columns=(value_column,))

    column = pd.to_numeric(df[value_column], errors="coerce")
    low, high = column.min(), column.max()
    print(f"Scaling {len(df):,} values from range [{low}, {high}] into [0, 1]...")
    normalized = column * 0 if (pd.isna(low) or high == low) else (column - low) / (high - low)

    target = new_column_name.strip() if new_column_name and new_column_name.strip() else value_column
    df[target] = normalized

    save_csv(df, csv_name, csv_root)
    if target == value_column:
        print(f"Success! Overwrote '{value_column}' in place with its 0-1 normalized values ({len(df):,} rows).")
    else:
        print(f"Success! Wrote 0-1 normalized values of '{value_column}' into new column '{target}' ({len(df):,} rows).")


def hierarchical_cluster(
    csv_name: str,
    topic_column: str = "topic_id",
    embedding_column: str = "5d",
    output_column: str = "hcluster",
    n_clusters: int = 10,
    csv_root: str | Path | None = None,
):
    """Agglomerate an existing topic assignment into a smaller number of hierarchical
    "super-clusters". Each topic is reduced to the centroid of its members'
    `embedding_column` vectors; the centroids are Ward-linked and the tree is cut into
    `n_clusters` groups, so related fine-grained topics collapse into a few broad
    themes. A top-down complement to HDBSCAN's flat `cluster`: same partition, coarser
    grain, and every topic lands in a theme (only noise stays -1)."""
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import pdist

    df = load_csv(csv_name, csv_root, columns=(topic_column, embedding_column))

    topic_num = pd.to_numeric(df[topic_column], errors="coerce")
    valid = topic_num.notna() & (topic_num != -1) & df[embedding_column].notna()
    topic_ids = sorted(topic_num[valid].astype(int).unique())
    if len(topic_ids) < 2:
        raise ValueError("Need at least two non-noise topics to agglomerate.")

    reporter = ProgressReporter(f"Building centroids for {len(topic_ids)} topics", len(topic_ids))
    centroids = []
    for i, topic_id in enumerate(topic_ids, start=1):
        members = df[valid & (topic_num == topic_id)]
        centroids.append(stacked_vectors(members[embedding_column]).mean(axis=0))
        reporter.update(i)

    k = max(2, min(int(n_clusters), len(topic_ids)))
    print(f"Ward-linking {len(topic_ids)} centroids and cutting the tree into {k} super-clusters...")
    linkage_matrix = linkage(pdist(np.vstack(centroids)), method="ward")
    super_ids = fcluster(linkage_matrix, t=k, criterion="maxclust")
    topic_to_super = {topic: int(super_id) for topic, super_id in zip(topic_ids, super_ids)}

    mapped = topic_num.map(topic_to_super)
    df[output_column] = mapped.fillna(-1).astype(int)
    assigned = int(mapped.notna().sum())

    save_csv(df, csv_name, csv_root)
    sizes = df[output_column].value_counts().drop(index=-1, errors="ignore").sort_index()
    print(f"Success! Mapped {len(topic_ids)} topics onto {k} super-clusters in '{output_column}' "
          f"({assigned:,} rows assigned). Sizes: {sizes.to_dict()}")
