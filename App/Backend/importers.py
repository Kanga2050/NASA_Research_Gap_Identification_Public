"""Import functions: fetch raw data from the outside world into a brand-new CSV.

Both importers stream their rows to disk as they arrive (appending page by page, or
document by document) rather than buffering the whole corpus in memory, so a long
scrape or a large PDF collection survives an interruption with partial progress
intact -- which is why they write directly instead of going through `save_csv`.

Both produce a `text` column holding the embeddable prose, the canonical raw-text
column name across the platform, so `combine_csvs` unions their outputs cleanly and
`embed_text` -> `reduce_dimensionality` -> `cluster` -> `label_topics` runs on either.

`requests`, PyMuPDF and spaCy are imported inside the functions: the task engine loads
this module to run either importer, and neither should pay for the other's stack.
"""
from __future__ import annotations

import html
import os
import re
import time
from pathlib import Path

import pandas as pd

from .backend_utils import progress_line
from App.Servers.storage_paths import resolve_csv_path, resolve_pdf_folder

# Identifies us to the OpenAlex and Crossref "polite pools", which grant a higher
# rate limit to requests that carry a contact address.
CONTACT_EMAIL = "shauryachauhan2050@gmail.com"


# --------------------------------------------------------------------------- #
# OpenAlex
# --------------------------------------------------------------------------- #
OPENALEX_URL = "https://api.openalex.org/works"
OPENALEX_COLUMNS = [
    "openalex_id", "title", "doi", "text", "publish_time",
    "authors", "journal", "pmcid", "pubmed_id",
]


def _inverted_index_to_text(index: dict) -> str:
    """OpenAlex ships abstracts as a {word: [positions]} inverted index; rebuild the
    prose by sorting every (position, word) pair back into reading order."""
    if not index:
        return ""
    words = [(pos, word) for word, positions in index.items() for pos in positions]
    words.sort()
    return " ".join(word for _, word in words)


def _openalex_row(paper: dict) -> dict | None:
    """One OpenAlex work -> one CSV row, or None if it has no usable abstract."""
    abstract = _inverted_index_to_text(paper.get("abstract_inverted_index", {}))
    if not abstract.strip():
        return None

    authors = [
        name for name in (
            author.get("author", {}).get("display_name", "")
            for author in paper.get("authorships", [])
        ) if name
    ]

    location = paper.get("primary_location") or {}
    journal = (location.get("source") or {}).get("display_name", "")

    return {
        "openalex_id": paper.get("id", ""),
        "title": paper.get("title", ""),
        "doi": paper.get("doi", ""),
        "text": abstract,
        "publish_time": paper.get("publication_date", ""),
        "authors": "; ".join(authors),
        "journal": journal,
        "pmcid": paper.get("ids", {}).get("pmcid", ""),
        "pubmed_id": paper.get("ids", {}).get("pmid", ""),
    }


def openalex_scraper(topic, csv_name: str = "scraped", limit: int = 10000, csv_root: str | Path | None = None):
    """Fetch up to `limit` works matching `topic` (that have an abstract) from the
    OpenAlex API into a brand-new CSV. Rows are streamed to disk in pages of 200 as
    they arrive, so partial progress survives an interruption."""
    import requests

    limit = int(limit)
    params = {
        "search": topic,
        "filter": "has_abstract:true",
        "per_page": 200,
        "cursor": "*",
        "mailto": CONTACT_EMAIL,
    }
    # Premium OpenAlex accounts get a higher rate limit via an API key; anonymous
    # (polite-pool) requests work fine without one.
    api_key = os.environ.get("OPENALEX_API_KEY")
    if api_key:
        params["api_key"] = api_key

    output_path = resolve_csv_path(csv_name, csv_root)
    pd.DataFrame(columns=OPENALEX_COLUMNS).to_csv(output_path, index=False)
    print(f"Searching OpenAlex for '{topic}' (abstracts only); target up to {limit:,} papers → '{csv_name}.csv'.")

    collected = 0
    while params["cursor"] and collected < limit:
        try:
            print(progress_line(f"Downloading '{topic}' papers", collected, limit))
            response = requests.get(OPENALEX_URL, params=params, timeout=60)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                print(f"OpenAlex returned no more results; stopping at {collected:,} papers.")
                break

            batch = []
            for paper in results:
                row = _openalex_row(paper)
                if row is None:
                    continue
                batch.append(row)
                collected += 1
                if collected >= limit:
                    break

            if batch:
                pd.DataFrame(batch, columns=OPENALEX_COLUMNS).to_csv(
                    output_path, mode="a", header=False, index=False
                )

            params["cursor"] = data.get("meta", {}).get("next_cursor")
            time.sleep(0.1)
        except Exception as exc:
            print(f"Stopped early after an error ({exc}); {collected:,} papers already saved.")
            break

    print(progress_line(f"Downloading '{topic}' papers", collected, min(limit, max(collected, 1))))
    print(f"Success! Saved {collected:,} '{topic}' papers (with abstracts) to new file '{csv_name}.csv'.")


# --------------------------------------------------------------------------- #
# PDF collections
# --------------------------------------------------------------------------- #
PDF_COLUMNS = [
    "text", "source_file", "source", "doi", "title",
    "authors", "journal", "publish_time", "chunk_index",
]

CROSSREF_URL = "https://api.crossref.org/works/"

# Drop fragments below this many words -- stray page numbers, running headers and
# nav-bar leftovers ("here", "Loading...") that would only be embedding noise.
MIN_CHUNK_WORDS = 5


def _build_sentencizer():
    """A blank English pipeline with just a rule-based sentence splitter -- fast enough
    for 500k-word survey books, unlike the full dependency parser."""
    import spacy

    nlp = spacy.blank("en")
    nlp.add_pipe("sentencizer")
    nlp.max_length = 3_000_000
    return nlp


def _clean_text(text: str) -> str:
    """Rejoin words broken across a line by a hyphen and collapse whitespace, so the
    sentence splitter sees flowing prose rather than PDF line wrapping."""
    text = text.replace("\r", "\n")
    text = re.sub(r"-\s*\n\s*", "", text)   # de-hyphenate word-\n-continuation
    return re.sub(r"\s+", " ", text).strip()


def _pack_sentences(sentences, chunk_words: int, overlap_words: int) -> list[str]:
    """Greedily combine whole sentences into ~chunk_words chunks, each starting with
    ~overlap_words carried over from the previous chunk. Never splits a sentence."""
    chunks = []
    current: list[tuple[str, int]] = []   # (sentence, word_count)
    current_words = 0
    pending_new = False                   # unemitted fresh content since the last chunk?

    for sentence in sentences:
        wc = len(sentence.split())
        if wc == 0:
            continue
        current.append((sentence, wc))
        current_words += wc
        pending_new = True

        if current_words >= chunk_words:
            chunks.append(" ".join(s for s, _ in current))
            # Keep trailing sentences worth ~overlap_words as the next chunk's head.
            tail, tail_words = [], 0
            for s, w in reversed(current):
                if tail_words >= overlap_words:
                    break
                tail.insert(0, (s, w))
                tail_words += w
            current, current_words = tail, tail_words
            pending_new = False

    # Emit the remainder only if it holds sentences not already fully in the last chunk
    # (otherwise the last chunk would be nothing but the previous chunk's overlap tail).
    if pending_new and current:
        chunks.append(" ".join(s for s, _ in current))
    return chunks


def _derive_doi(stem: str) -> str:
    """OSDR filenames are DOIs with the first '/' written as '_'
    (`10.1002_ajb2.1223` -> `10.1002/ajb2.1223`). Numeric Decadal filenames have no DOI."""
    match = re.match(r"^(10\.\d+)_(.+)$", stem)
    return f"{match.group(1)}/{match.group(2)}" if match else ""


def _clean_meta_value(value) -> str:
    """Unescape entities, strip embedded XML/JATS tags (Crossref titles carry `<scp>`,
    `<i>` and friends) and collapse whitespace."""
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _crossref_lookup(doi: str, cache: dict) -> dict:
    """Best-effort Crossref metadata for a DOI. Returns {} on any failure, so the
    caller falls back to the PDF's embedded metadata."""
    import requests

    if not doi:
        return {}
    if doi in cache:
        return cache[doi]

    result = {}
    try:
        response = requests.get(f"{CROSSREF_URL}{doi}", params={"mailto": CONTACT_EMAIL}, timeout=15)
        if response.status_code == 200:
            message = response.json().get("message", {})
            authors = "; ".join(
                f"{a.get('given', '')} {a.get('family', '')}".strip()
                for a in message.get("author", [])
            ).strip()
            year = ""
            for key in ("published", "published-print", "published-online", "issued"):
                parts = (message.get(key) or {}).get("date-parts", [[]])
                if parts and parts[0]:
                    year = str(parts[0][0])
                    break
            result = {
                "authors": _clean_meta_value(authors),
                "title": _clean_meta_value((message.get("title") or [""])[0]),
                "journal": _clean_meta_value((message.get("container-title") or [""])[0]),
                "publish_time": year,
            }
    except Exception:
        result = {}

    cache[doi] = result
    time.sleep(0.05)   # be polite to the Crossref pool
    return result


def _resolve_metadata(path: Path, doc, source_label: str, enrich: bool, cache: dict) -> dict:
    """Per-document metadata: Crossref (by DOI) preferred, the PDF's own embedded
    metadata as the fallback, `source_label` as the last resort for the journal."""
    pdf_md = doc.metadata or {}
    meta = {
        "doi": _derive_doi(path.stem),
        "title": _clean_meta_value(pdf_md.get("title")),
        "authors": _clean_meta_value(pdf_md.get("author")),
        "journal": "",
        "publish_time": "",
    }
    if enrich and meta["doi"]:
        for key, value in _crossref_lookup(meta["doi"], cache).items():
            if value:
                meta[key] = value   # Crossref wins wherever it has the field
    if not meta["journal"]:
        meta["journal"] = source_label
    return meta


def _collect_pdfs(folders, pdf_root) -> tuple[list[tuple[str, Path]], list[str]]:
    """Resolve comma-separated collection names to (folder_name, pdf_path) pairs,
    checking the caller's own PDF area first and then the public library."""
    names = [n.strip() for n in str(folders).split(",") if n.strip()]
    if not names:
        raise ValueError("Provide at least one PDF collection folder name.")

    items: list[tuple[str, Path]] = []
    for name in names:
        directory = resolve_pdf_folder(name, pdf_root)
        if directory is None:
            print(f"Skipping unknown PDF folder '{name}' (not in your area or the public library).")
            continue
        found = sorted(directory.glob("*.pdf"))
        if not found:
            print(f"Skipping '{name}' (no PDFs inside).")
            continue
        items.extend((name, path) for path in found)

    if not items:
        raise ValueError(f"No PDFs found in the requested folder(s): {', '.join(names)}.")
    return items, names


def chunk_pdfs(
    folders,
    csv_name: str = "pdf_chunks",
    source_label: str = "",
    chunk_words: int = 250,
    overlap_words: int = 40,
    enrich: bool = True,
    csv_root: str | Path | None = None,
    pdf_root: str | Path | None = None,
):
    """Turn one or more PDF collections into a corpus CSV, one row per chunk.

    Each PDF's text is extracted (PyMuPDF), split into sentences (spaCy's rule-based
    sentencizer), then greedily packed into ~`chunk_words`-word chunks with
    ~`overlap_words` of overlap -- always on whole-sentence boundaries, so a chunk
    never cuts a sentence in half. `source_label` tags each row's origin (when blank,
    each row is tagged with the collection folder it came from); `enrich` looks
    OSDR-style DOI filenames up on Crossref for clean authors/journal/title.
    """
    import fitz  # PyMuPDF

    chunk_words, overlap_words, enrich = int(chunk_words), int(overlap_words), bool(enrich)
    pdf_items, names = _collect_pdfs(folders, pdf_root)

    output_path = resolve_csv_path(csv_name, csv_root)
    pd.DataFrame(columns=PDF_COLUMNS).to_csv(output_path, index=False)
    print(f"Chunking {len(pdf_items)} PDFs from {len(names)} folder(s) → '{csv_name}.csv' "
          f"(~{chunk_words} words/chunk, ~{overlap_words} overlap, enrich={enrich}).")

    nlp = _build_sentencizer()
    crossref_cache: dict = {}
    total_chunks = 0

    for i, (folder_name, path) in enumerate(pdf_items, start=1):
        print(progress_line(f"Chunking PDFs (last: {path.name})", i - 1, len(pdf_items)))
        try:
            doc = fitz.open(path)
        except Exception as exc:
            print(f"Skipping '{path.name}' (could not open: {exc}).")
            continue

        row_source = source_label or folder_name
        meta = _resolve_metadata(path, doc, row_source, enrich, crossref_cache)

        # Segment page by page so a single spaCy call never exceeds max_length, but
        # pack across the whole document so chunks flow past page breaks.
        sentences = []
        for page in doc:
            cleaned = _clean_text(page.get_text())
            if cleaned:
                sentences.extend(sent.text.strip() for sent in nlp(cleaned).sents)
        doc.close()

        rows = [{
            "text": chunk,
            "source_file": path.name,
            "source": row_source,
            "doi": meta["doi"],
            "title": meta["title"],
            "authors": meta["authors"],
            "journal": meta["journal"],
            "publish_time": meta["publish_time"],
            "chunk_index": idx,
        } for idx, chunk in enumerate(
            c for c in _pack_sentences(sentences, chunk_words, overlap_words)
            if len(c.split()) >= MIN_CHUNK_WORDS
        )]

        if rows:
            pd.DataFrame(rows, columns=PDF_COLUMNS).to_csv(output_path, mode="a", header=False, index=False)
            total_chunks += len(rows)

    print(progress_line("Chunking PDFs", len(pdf_items), len(pdf_items)))
    print(f"Success! Wrote {total_chunks:,} chunks from {len(pdf_items)} PDFs to new file '{csv_name}.csv'.")
