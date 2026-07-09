"""Shared spaCy setup for keyword extraction (Word_Frequency, Label_Topics,
Distance_Map all lemmatize + drop stopwords + rank by frequency the same way)."""
from __future__ import annotations

from collections import Counter

import spacy

MAX_TEXT_CHARS = 100000

try:
    NLP = spacy.load("en_core_web_sm", disable=["parser", "ner"])
    HAS_POS_TAGS = True
except OSError:
    NLP = spacy.blank("en")
    HAS_POS_TAGS = False


def lemmas(doc) -> list[str]:
    """Lowercased, stopword-filtered lemmas; nouns/adjectives only when the loaded
    model has POS tags (falls back to all alpha tokens for a blank pipeline)."""
    if HAS_POS_TAGS:
        return [
            (token.lemma_ or token.text).lower() for token in doc
            if token.is_alpha and not token.is_stop and token.pos_ in ("NOUN", "ADJ")
        ]
    return [
        (token.lemma_ or token.text).lower() for token in doc
        if token.is_alpha and not token.is_stop
    ]


def top_keywords(texts, top_n: int = 3) -> str:
    """Top `top_n` comma-joined keywords describing the pooled `texts` (lemmatized,
    stopword-filtered, ranked by frequency) -- the label Distance Map and
    label_topics show for a topic."""
    doc = NLP(" ".join(texts)[:MAX_TEXT_CHARS])
    return ", ".join(word for word, _ in Counter(lemmas(doc)).most_common(top_n))
