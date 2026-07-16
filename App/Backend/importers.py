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


# --------------------------------------------------------------------------- #
# NASA Task Book reports
#
# Unlike a journal PDF (free-flowing prose -> many chunks), every Task Book PDF is a
# single ColdFusion-generated form with the SAME fixed set of labelled fields, so it
# parses to exactly ONE structured row per report -- authors, dates, funding and the
# project narrative pulled out of their form fields rather than chunked. Downloaded by
# Data_Import/taskbook_scraper.py into the Taskbook_Search_Pdfs / Taskbook_Bibliography_Pdfs
# collections.
# --------------------------------------------------------------------------- #
TASKBOOK_COLUMNS = [
    "text", "title", "authors", "publish_time", "fiscal_year",
    "start_date", "end_date", "division", "program", "organization",
    "project_type", "funding_source", "grant_number", "co_investigators",
    "bibliography", "source", "source_file", "task_id",
]

# Every field label the form emits, IN THE ORDER THEY APPEAR. The parser walks this
# list once from the top of the document, so the text between one label and the next
# is that label's value -- which is why the order matters and the list must be
# complete. Labels that wrap across two lines in the PDF (e.g. "Solicitation / Funding
# Source:") are written here with a single space; the matcher treats every space as
# "any run of whitespace", so a space or a line break both match.
_TASKBOOK_LABELS = [
    "Fiscal Year:", "Task Last Updated:", "PI Name:", "Project Title:",
    "Division Name:", "Program/Discipline:",
    "Program/Discipline-- Element/Subdiscipline:", "Joint Agency Name:",
    "TechPort:", "Human Research Program Elements:", "Human Research Program Risks:",
    "Space Biology Element:", "Space Biology Cross-Element Discipline:",
    "Space Biology Special Category:", "PI Email:", "Fax:",
    "PI Organization Type:", "Phone:", "Organization Name:",
    "PI Address 1:", "PI Address 2:", "PI Web Page:", "City:", "State:",
    "Zip Code:", "Congressional District:", "Comments:", "Project Type:",
    "Solicitation / Funding Source:", "Start Date:", "End Date:",
    "No. of Post Docs:", "No. of PhD Degrees:", "No. of PhD Candidates:",
    "No. of Master' Degrees:", "No. of Master's Candidates:",
    "No. of Bachelor's Degrees:", "No. of Bachelor's Candidates:",
    "Monitoring Center:", "Contact Monitor:", "Contact Phone:", "Contact Email:",
    "Flight Program:", "Flight Assignment:", "Key Personnel Changes/Previous PI:",
    "COI Name (Institution):", "Grant/Contract No.:", "Performance Goal No.:",
    "Performance Goal Text:", "Task Description:",
    "Rationale for HRP Directed Research:", "Research Impact/Earth Benefits:",
    "Task Progress:", "Bibliography Type:",
]
_TASKBOOK_LABEL_RX = {
    label: re.compile(r"\s+".join(re.escape(token) for token in label.split()))
    for label in _TASKBOOK_LABELS
}

# Extracting the whole document interleaves each page's header/footer into the text;
# these lines are boilerplate, not report content, so they are dropped before parsing.
_TASKBOOK_FURNITURE_RX = re.compile(
    r"^(Page \d+ of \d+|Task Book Report|Generated on:\s*[\d/]+)\s*$"
)
_YEAR_RX = re.compile(r"(19|20)\d{2}")

# The narrative sections, concatenated into the embeddable `text` column in this order.
_TASKBOOK_NARRATIVE = [
    "Task Description:", "Research Impact/Earth Benefits:", "Task Progress:",
]


def _strip_furniture(text: str) -> str:
    """Drop the per-page "Page 1 of 2 / Task Book Report / Generated on:" boilerplate,
    which the extractor splices into the middle of the text at every page break."""
    return "\n".join(
        line for line in text.splitlines()
        if not _TASKBOOK_FURNITURE_RX.match(line.strip())
    )


def _tb_clean(value: str) -> str:
    """Rejoin hyphen-broken words and collapse all whitespace to single spaces, so a
    field wrapped across several PDF lines reads as one flowing string."""
    value = re.sub(r"-\s*\n\s*", "", value.replace("\r", "\n"))
    return re.sub(r"\s+", " ", value).strip()


def _tb_clean_list(value: str) -> str:
    """Like `_tb_clean` but for one-entry-per-line fields (the co-investigator block):
    keep the entries distinct by joining them with '; ' instead of a space."""
    parts = [re.sub(r"\s+", " ", line).strip() for line in value.replace("\r", "\n").split("\n")]
    return "; ".join(part for part in parts if part)


def _parse_taskbook_report(text: str) -> dict:
    """Slice a Task Book PDF's text into its form fields by walking `_TASKBOOK_LABELS`
    once from the top: each label's value is the text up to the next label found."""
    text = _strip_furniture(text)

    spans = []                       # (label, value_start) for every label present
    cursor = 0
    for label in _TASKBOOK_LABELS:
        match = _TASKBOOK_LABEL_RX[label].search(text, cursor)
        if match:                    # tolerate an absent field: skip it, keep the cursor
            spans.append((label, match.start(), match.end()))
            cursor = match.end()

    fields = {}
    for i, (label, _start, value_start) in enumerate(spans):
        value_end = spans[i + 1][1] if i + 1 < len(spans) else len(text)
        fields[label] = text[value_start:value_end]
    return fields


def _taskbook_row(fields: dict, folder_name: str, source_label: str, source_file: str) -> dict:
    """Map parsed form fields onto the output schema, choosing a canonical `text` and a
    parseable `publish_time` year."""
    fiscal_year = _tb_clean(fields.get("Fiscal Year:", ""))
    start_date = _tb_clean(fields.get("Start Date:", ""))
    end_date = _tb_clean(fields.get("End Date:", ""))

    # `publish_time` is the platform's date column (feeds extract_year/to_date): use the
    # fiscal year, falling back to the project start/end year if the FY field is blank.
    year = ""
    for candidate in (fiscal_year, start_date, end_date):
        found = _YEAR_RX.search(candidate)
        if found:
            year = found.group(0)
            break

    # The embeddable prose = the substantive narrative sections stitched together (the
    # metadata fields are provenance/filters, not semantic content). Joined on a single
    # space to keep every cell one physical line, like the platform's other `text`
    # corpora -- multi-line cells would break the catalog's line-based row count.
    narrative = [_tb_clean(fields.get(section, "")) for section in _TASKBOOK_NARRATIVE]
    text = " ".join(section for section in narrative if section)

    return {
        "text": text,
        "title": _tb_clean(fields.get("Project Title:", "")),
        "authors": _tb_clean(fields.get("PI Name:", "")),
        "publish_time": year,
        "fiscal_year": fiscal_year,
        "start_date": start_date,
        "end_date": end_date,
        "division": _tb_clean(fields.get("Division Name:", "")),
        "program": _tb_clean(fields.get("Program/Discipline:", "")),
        "organization": _tb_clean(fields.get("Organization Name:", "")),
        "project_type": _tb_clean(fields.get("Project Type:", "")),
        "funding_source": _tb_clean(fields.get("Solicitation / Funding Source:", "")),
        "grant_number": _tb_clean(fields.get("Grant/Contract No.:", "")),
        "co_investigators": _tb_clean_list(fields.get("COI Name (Institution):", "")),
        "bibliography": _tb_clean(fields.get("Bibliography Type:", "")),
        "source": source_label or folder_name,
        "source_file": source_file,
        "task_id": Path(source_file).stem,
    }


def parse_taskbook_pdfs(
    folders,
    csv_name: str = "taskbook_reports",
    source_label: str = "",
    csv_root: str | Path | None = None,
    pdf_root: str | Path | None = None,
):
    """Turn one or more NASA Task Book PDF collections into a structured CSV, one row
    per report.

    Every Task Book PDF is the same fixed ColdFusion form, so its labelled fields are
    pulled straight out into columns -- `authors` (the PI), `publish_time`/`fiscal_year`
    and start/end dates, `division`, `program`, `organization`, `funding_source`,
    `grant_number`, `co_investigators` and the `bibliography` -- with the project's
    narrative sections (description, Earth-benefit impact, progress) concatenated into
    an embeddable `text` column. `source_label` tags each row's origin (defaults to the
    collection folder name). Point it at the Taskbook_Search_Pdfs /
    Taskbook_Bibliography_Pdfs collections; feed `text` through embed_text ->
    reduce_dimensionality -> cluster -> label_topics to match Space_Biology's columns.
    """
    import fitz  # PyMuPDF

    pdf_items, names = _collect_pdfs(folders, pdf_root)

    output_path = resolve_csv_path(csv_name, csv_root)
    pd.DataFrame(columns=TASKBOOK_COLUMNS).to_csv(output_path, index=False)
    print(f"Parsing {len(pdf_items)} Task Book PDFs from {len(names)} folder(s) → '{csv_name}.csv'.")

    written = empty_text = 0
    for i, (folder_name, path) in enumerate(pdf_items, start=1):
        print(progress_line(f"Parsing Task Book reports (last: {path.name})", i - 1, len(pdf_items)))
        try:
            doc = fitz.open(path)
            text = "".join(page.get_text() for page in doc)
            doc.close()
        except Exception as exc:
            print(f"Skipping '{path.name}' (could not read: {exc}).")
            continue

        fields = _parse_taskbook_report(text)
        row = _taskbook_row(fields, folder_name, source_label, path.name)
        if not row["text"]:
            empty_text += 1

        # Stream each report to disk as it is parsed, so a long run survives an
        # interruption with partial progress intact (same contract as the importers above).
        pd.DataFrame([row], columns=TASKBOOK_COLUMNS).to_csv(
            output_path, mode="a", header=False, index=False
        )
        written += 1

    print(progress_line("Parsing Task Book reports", len(pdf_items), len(pdf_items)))
    note = f" ({empty_text} had no narrative text)" if empty_text else ""
    print(f"Success! Wrote {written:,} Task Book reports to new file '{csv_name}.csv'{note}.")
