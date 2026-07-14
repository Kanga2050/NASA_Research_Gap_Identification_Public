"""Import function: turn one or more PDF *collections* into a Space_Biology-style CSV.

`folders` names PDF collections (comma-separated) that live under the caller's own
PDF area or the shared public library (`App/Backend/PDFs/<collection>/`). Each PDF's
text is extracted (PyMuPDF), split into sentences (spaCy's rule-based `sentencizer`),
then greedily packed into ~`chunk_words`-word chunks with ~`overlap_words` of overlap
-- always on whole-sentence boundaries, so a chunk never cuts a sentence in half.
One row per chunk. Metadata (authors, journal, title, year) is recovered per
document: OSDR-style filenames are DOIs, so we look them up on Crossref; everything
else falls back to the PDF's embedded metadata.

The output `text` column is the embeddable chunk -- feed it straight into
`embed_text` -> `reduce_dimensionality` -> `cluster` -> `label_topics` to give the
dataset the same columns as Space_Biology.csv, and `combine_csvs` will stack them.
"""
import html
import re
import time
from pathlib import Path

import fitz  # PyMuPDF
import pandas as pd
import requests
import spacy

from Backend.backend_utils import progress_line
from Servers.storage_paths import resolve_csv_path, resolve_pdf_folder

COLUMNS = [
    "text", "source_file", "source", "doi", "title",
    "authors", "journal", "publish_time", "chunk_index",
]

CROSSREF_URL = "https://api.crossref.org/works/"
CONTACT_EMAIL = "shauryachauhan2050@gmail.com"

# Drop fragments below this many words -- stray page numbers, headers and
# nav-bar leftovers ("here", "Loading...") that would just be embedding noise.
MIN_CHUNK_WORDS = 5


def _build_sentencizer():
    """A blank English pipeline with just a rule-based sentence splitter -- fast
    enough for 500k-word survey books, unlike the full dependency parser (which
    `nlp_utils.NLP` disables anyway)."""
    nlp = spacy.blank("en")
    nlp.add_pipe("sentencizer")
    nlp.max_length = 3_000_000
    return nlp


def _clean_text(text: str) -> str:
    """Join line-broken (hyphenated) words and collapse whitespace to single
    spaces so sentence splitting sees flowing prose, not PDF line wrapping."""
    text = text.replace("\r", "\n")
    text = re.sub(r"-\s*\n\s*", "", text)   # de-hyphenate word-\n-continuation
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _pack_sentences(sentences, chunk_words: int, overlap_words: int):
    """Greedily combine whole sentences into ~chunk_words chunks, each starting
    with ~overlap_words carried over from the previous chunk. Never splits a
    sentence."""
    chunks = []
    current = []          # list of (sentence, word_count)
    current_words = 0
    pending_new = False   # unemitted fresh content since the last chunk?

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

    # Emit the remainder only if it holds sentences not already fully in the last
    # chunk (avoids a trailing chunk that is nothing but the previous overlap tail).
    if pending_new and current:
        chunks.append(" ".join(s for s, _ in current))
    return chunks


def _derive_doi(stem: str) -> str:
    """OSDR filenames are DOIs with the first '/' written as '_'
    (`10.1002_ajb2.1223` -> `10.1002/ajb2.1223`). Numeric Decadal filenames have
    no DOI -> ''."""
    match = re.match(r"^(10\.\d+)_(.+)$", stem)
    return f"{match.group(1)}/{match.group(2)}" if match else ""


def _clean_meta_value(value: str) -> str:
    """Unescape entities, strip embedded XML/JATS tags (Crossref titles carry
    `<scp>`, `<i>` etc.) and collapse whitespace."""
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _crossref_lookup(doi: str, cache: dict) -> dict:
    """Best-effort Crossref metadata for a DOI. Returns {} on any failure so the
    caller falls back to embedded PDF metadata."""
    if not doi:
        return {}
    if doi in cache:
        return cache[doi]
    result = {}
    try:
        response = requests.get(
            f"{CROSSREF_URL}{doi}", params={"mailto": CONTACT_EMAIL}, timeout=15
        )
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
    """Per-document metadata: Crossref (by DOI) preferred, PDF embedded metadata as
    the fallback, `source_label` as the last resort for the journal/source field."""
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
                meta[key] = value   # Crossref wins when it has the field
    if not meta["journal"]:
        meta["journal"] = source_label
    return meta


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
    """Chunk the PDFs in one or more `folders` (comma-separated collection names,
    resolved under the caller's `pdf_root` then the public library) into one CSV.
    `source_label` tags each row's origin -- when blank, each row is tagged with the
    collection folder it came from. `chunk_words`/`overlap_words` size the
    sentence-aware chunks; `enrich` looks DOIs up on Crossref for clean
    authors/journal/title."""
    chunk_words = int(chunk_words)
    overlap_words = int(overlap_words)
    enrich = bool(enrich)

    # Resolve each requested collection to (folder_name, directory), skipping any
    # that don't exist under the user's area or the public library.
    names = [n.strip() for n in str(folders).split(",") if n.strip()]
    if not names:
        raise ValueError("Provide at least one PDF collection folder name.")
    pdf_items = []   # (folder_name, pdf_path)
    for name in names:
        directory = resolve_pdf_folder(name, pdf_root)
        if directory is None:
            print(f"Skipping unknown PDF folder '{name}' (not in your area or the public library).")
            continue
        found = sorted(directory.glob("*.pdf"))
        if not found:
            print(f"Skipping '{name}' (no PDFs inside).")
            continue
        pdf_items.extend((name, path) for path in found)
    if not pdf_items:
        raise ValueError(f"No PDFs found in the requested folder(s): {', '.join(names)}.")

    output_path = resolve_csv_path(csv_name, csv_root)
    pd.DataFrame(columns=COLUMNS).to_csv(output_path, index=False)
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

        # Segment page by page so a single spaCy call never exceeds max_length,
        # but pack across the whole document so chunks flow past page breaks.
        sentences = []
        for page in doc:
            cleaned = _clean_text(page.get_text())
            if cleaned:
                sentences.extend(sent.text.strip() for sent in nlp(cleaned).sents)
        doc.close()

        chunks = [c for c in _pack_sentences(sentences, chunk_words, overlap_words)
                  if len(c.split()) >= MIN_CHUNK_WORDS]
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
        } for idx, chunk in enumerate(chunks)]

        if rows:
            pd.DataFrame(rows, columns=COLUMNS).to_csv(output_path, mode="a", header=False, index=False)
            total_chunks += len(rows)

    print(progress_line("Chunking PDFs", len(pdf_items), len(pdf_items)))
    print(f"Success! Wrote {total_chunks:,} chunks from {len(pdf_items)} PDFs to new file '{csv_name}.csv'.")


if __name__ == "__main__":
    # Collections now live under the public library (App/Backend/PDFs/).
    chunk_pdfs("OSDR_Pdfs", "OSDR", source_label="OSDR")
    chunk_pdfs("Decadal_Survey_Pdfs", "Decadal_Survey", source_label="Decadal Survey")
