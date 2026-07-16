#!/usr/bin/env python3
"""
NASA Task Book PDF scraper
==========================

Downloads every task/report PDF exposed by the two public search sections of the
NASA Task Book (https://taskbook.nasa.gov/tbp/index.cfm) into two folders inside
this repo's public PDF library (``App/Backend/PDFs/``), so they become choosable
by the ``chunk_pdfs`` pipeline and show up in the web dashboard's "PDF
collections" card and the MCP ``list_pdf_folders`` tool with no further wiring.

    App/Backend/PDFs/Taskbook_Search_Pdfs/*.pdf         <- "Search Task Book"  (~2916)
    App/Backend/PDFs/Taskbook_Bibliography_Pdfs/*.pdf   <- "Search Bibliography" (report PDFs
                                                            behind ~28k citations, de-duped by id)

How the site works (established by exploration)
-----------------------------------------------
* Both search forms POST to ``index.cfm`` and hold the result set in a
  ColdFusion *session* -- the results cannot be retrieved by a cookie-less HTTP
  client, so the id-collection phase must run inside a live browser (Selenium).
* Each result row links to ``index.cfm?action=public_query_taskbook_content&TASKID=<HEX>``.
  The "Download ... report in PDF" button on that entry is simply
  ``tbpdf.cfm?id=<HEX>`` -- a *stateless, public* endpoint returning ``application/pdf``.
  So once we have the ids we can download the PDFs with plain parallel HTTP.
* Results paginate via GET: ``index.cfm?action=sort&...&p=N`` (task book) and
  ``index.cfm?action=bib_sort&...&p=N`` (bibliography). Any page number can be
  jumped to directly within a search session, so collection parallelises cleanly
  across several independent browser sessions.

* The server enforces an Apache 429 rate limit (no ``Retry-After``). Blasting it
  with 50 concurrent requests trips a multi-minute cooldown, so downloads run
  through an *adaptive* global token-bucket limiter: it targets a steady request
  rate, halves the rate whenever a 429 is seen, and recovers slowly on sustained
  success. Requests that 429 are retried with exponential backoff (a valid id is
  never dropped just because we were throttled).

Two phases
----------
1. COLLECT (Selenium, parallel browser sessions): open the broad search (all three
   programs), set the largest page size, read the page count, then fan the pages
   out across ``--collect-workers`` headless browsers and scrape every task id.
2. DOWNLOAD (requests + threads, rate-limited): fetch ``tbpdf.cfm?id=<id>`` for
   every unique id with ``--download-workers`` concurrent workers whose aggregate
   throughput is capped by the adaptive limiter. Downloads are validated (%PDF
   magic), resumable (existing valid files are skipped) and retried with backoff.

Run it straight from its location -- it finds ``App/Backend/PDFs`` by walking up
from this file, so paths work regardless of the current working directory:

    python Data_Import/taskbook_scraper.py                 # both sections, full
    python Data_Import/taskbook_scraper.py --section taskbook
    python Data_Import/taskbook_scraper.py --collect-only   # count ids, download nothing
    python Data_Import/taskbook_scraper.py --section taskbook --max-pages 2   # quick smoke test
"""
from __future__ import annotations

import argparse
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
BASE = "https://taskbook.nasa.gov/tbp/index.cfm"
PDF_URL = "https://taskbook.nasa.gov/tbp/tbpdf.cfm?id={id}"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/150.0 Safari/537.36")

# Per-section settings. "Search Task Book" lists one row per task; "Search
# Bibliography" lists one row per publication, each pointing back at the
# fiscal-year report whose PDF we download (many citations share a report id,
# so the id set is de-duped -- one file per unique report).
SECTIONS = {
    "taskbook": {
        "folder": "Taskbook_Search_Pdfs",
        "search_url": BASE,
        "start_locator": (By.ID, "Search"),
        "page_action": "sort",
        "page_size": "50",          # task-book page-size selector maxes out at 50
    },
    "bibliography": {
        "folder": "Taskbook_Bibliography_Pdfs",
        "search_url": BASE + "?action=bib_search",
        "start_locator": (By.XPATH, "//input[@type='Submit' or @type='submit']"),
        "page_action": "bib_sort",
        "page_size": None,          # its results form breaks on a page-size submit;
                                    # use the site default (50/page -> 564 pages)
    },
}

# Every result-row detail link carries the id we need; both sections use this URL.
ID_RE = re.compile(r"public_query_taskbook_content&(?:amp;)?TASKID=([0-9A-Fa-f]+)")
TOTAL_RE = re.compile(r"Page No\.\s*\d+\s*of\s*([\d,]+)")

_print_lock = threading.Lock()


def log(msg: str) -> None:
    """Timestamped, line-buffered log line (safe to call from many threads)."""
    with _print_lock:
        print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


# --------------------------------------------------------------------------- #
# Adaptive rate limiter (shared by all download threads)
# --------------------------------------------------------------------------- #
class RateLimiter:
    """Global token-bucket limiter that adapts to the server's 429 responses.

    Threads call :meth:`acquire` before every request. A 429 calls
    :meth:`penalize` (halve the rate); a sustained run of successes calls
    :meth:`reward` (nudge the rate back up toward ``max_rate``). This keeps the
    whole download pool just under the server's limit without hand-tuning.
    """

    def __init__(self, rate: float, max_rate: float, penalty: float = 30.0,
                 min_rate: float = 0.5):
        self.rate = float(rate)
        self.max_rate = float(max_rate)
        self.min_rate = float(min_rate)
        self.penalty = float(penalty)        # global quiet pause applied on a 429
        self._allowance = 0.0                 # start empty: no initial burst
        self._last = time.monotonic()
        self._paused_until = 0.0
        self._ok_streak = 0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                if now < self._paused_until:         # everyone stays silent
                    wait = self._paused_until - now
                else:
                    self._allowance += (now - self._last) * self.rate
                    self._last = now
                    if self._allowance > self.rate:  # cap burst to ~1s of tokens
                        self._allowance = self.rate
                    if self._allowance >= 1.0:
                        self._allowance -= 1.0
                        return
                    wait = (1.0 - self._allowance) / self.rate
            time.sleep(min(wait, 2.0))

    def penalize(self) -> None:
        """A 429 was seen: halve the rate AND pause the whole pool so the block
        (which every request during it resets) gets a clean quiet gap to clear."""
        with self._lock:
            now = time.monotonic()
            if now < self._paused_until:             # already paused by another thread
                return
            self.rate = max(self.min_rate, self.rate * 0.5)
            self._paused_until = now + self.penalty
            self._last = self._paused_until          # no token accrual while paused
            self._allowance = 0.0
            self._ok_streak = 0
            newrate = self.rate
        log(f"[!] 429 rate-limit hit -> pausing ALL downloads {self.penalty:.0f}s, "
            f"rate now {newrate:.1f}/s")

    def reward(self) -> None:
        with self._lock:
            self._ok_streak += 1
            if self._ok_streak >= 25 and self.rate < self.max_rate:
                self.rate = min(self.max_rate, self.rate * 1.15)
                self._ok_streak = 0

    @property
    def current_rate(self) -> float:
        return self.rate


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
def find_pdf_root(start: Path) -> Path:
    """Walk up from ``start`` to the repo's public PDF library ``App/Backend/PDFs``.

    Resolving relative to this file (not the CWD) is what lets the script be run
    "from its location" and still land the PDFs in the right place -- the same
    directory the MCP getter and the web dashboard scan live on every request.
    """
    for base in [start, *start.parents]:
        candidate = base / "App" / "Backend" / "PDFs"
        if candidate.is_dir():
            return candidate
    sys.exit("Could not locate App/Backend/PDFs above this script's location.")


# --------------------------------------------------------------------------- #
# Selenium (collection phase)
# --------------------------------------------------------------------------- #
def make_driver(page_load_timeout: int = 90) -> webdriver.Chrome:
    """A headless Chrome tuned for scraping (no images, eager load)."""
    opts = Options()
    for arg in (
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--window-size=1400,1000",
        "--blink-settings=imagesEnabled=false",
    ):
        opts.add_argument(arg)
    opts.add_argument(f"--user-agent={UA}")
    opts.page_load_strategy = "eager"
    driver = webdriver.Chrome(options=opts)   # Selenium Manager fetches the driver
    driver.set_page_load_timeout(page_load_timeout)
    return driver


def page_url(section: str, p: int) -> str:
    return f"{BASE}?action={SECTIONS[section]['page_action']}&sort=asc&col=pi&p={p}"


def open_search(driver: webdriver.Chrome, section: str) -> int:
    """Submit the broad search, enlarge the page size, return the page count.

    The default form has all three programs (Human Research / Space Biology /
    Physical Sciences) checked, so a plain "Start Search" returns the whole
    catalog -- 2916 tasks / ~28k bibliography records.
    """
    cfg = SECTIONS[section]
    driver.get(cfg["search_url"])
    btn = WebDriverWait(driver, 30).until(EC.element_to_be_clickable(cfg["start_locator"]))
    driver.execute_script("arguments[0].click();", btn)
    WebDriverWait(driver, 60).until(
        lambda d: TOTAL_RE.search(d.page_source) or ID_RE.search(d.page_source)
    )

    def parse_total():
        m = TOTAL_RE.search(driver.page_source)
        return int(m.group(1).replace(",", "")) if m else None

    # Page count at the site's default page size -- read BEFORE touching the
    # page-size selector, so a failed enlarge can't collapse the total to 1.
    default_total = parse_total() or 1

    # Optionally enlarge the page size (fewer pages to fetch). Some result pages
    # break on this submit, so on ANY failure keep the default page size + count.
    if cfg.get("page_size"):
        try:
            Select(driver.find_element(By.NAME, "CountPerPage")).select_by_value(cfg["page_size"])
            driver.execute_script("document.getElementsByName('CountPerPage')[0].form.submit();")
            WebDriverWait(driver, 30).until(lambda d: TOTAL_RE.search(d.page_source))
            enlarged = parse_total()
            if enlarged:
                return enlarged
        except Exception as exc:
            log(f"[{section}] page-size change failed ({type(exc).__name__}); "
                f"using site default ({default_total} pages)")
            try:   # reset the session to a clean page-1 results state
                driver.get(page_url(section, 1))
                WebDriverWait(driver, 30).until(lambda d: ID_RE.search(d.page_source))
            except Exception:
                pass
    return default_total


def scrape_pages(driver, section, pages, out_ids, ids_lock, page_delay, on_page) -> None:
    """Visit each page number in ``pages`` and add its task ids to ``out_ids``.

    Handles the server's 429 page (backoff + retry) so heavy paging doesn't drop
    pages, and paces requests with ``page_delay`` to stay under the limiter.
    """
    for p in pages:
        for attempt in range(6):
            try:
                driver.get(page_url(section, p))
                html = driver.page_source
                if "429 Too Many Requests" in html or "Too Many Requests" in html:
                    time.sleep(min(30, 3 * (attempt + 1)) + random.uniform(0, 1))
                    continue
                found = ID_RE.findall(html)
                if found:
                    with ids_lock:
                        out_ids.update(found)
                break
            except Exception as exc:
                if attempt == 5:
                    log(f"[{section}] page {p} failed after retries: {exc!r}")
                time.sleep(1.5 * (attempt + 1))
        on_page()
        if page_delay:
            time.sleep(page_delay)


def collect_ids(section: str, workers: int, page_delay: float, max_pages: int = 0) -> set[str]:
    """Collect every unique task id for a section, fanning pages across browsers."""
    boot = make_driver()
    try:
        total = open_search(boot, section)
    finally:
        boot.quit()
    if max_pages:
        total = min(total, max_pages)
    per_page = SECTIONS[section]["page_size"] or "site-default"
    log(f"[{section}] {total} result page(s) at {per_page} per page")

    all_pages = list(range(1, total + 1))
    workers = max(1, min(workers, len(all_pages)))
    # Round-robin split so each worker covers the full range evenly.
    chunks = [all_pages[i::workers] for i in range(workers)]

    out_ids: set[str] = set()
    ids_lock = threading.Lock()
    progress = {"done": 0}
    prog_lock = threading.Lock()

    def on_page():
        with prog_lock:
            progress["done"] += 1
            done = progress["done"]
        if done % 5 == 0 or done == total:
            log(f"[{section}][collect] page {done}/{total}  ids={len(out_ids)}")

    def run_worker(pages):
        if not pages:
            return
        driver = make_driver()
        try:
            open_search(driver, section)          # this worker's own search session
            scrape_pages(driver, section, pages, out_ids, ids_lock, page_delay, on_page)
        finally:
            driver.quit()

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for fut in as_completed([ex.submit(run_worker, c) for c in chunks]):
            fut.result()

    log(f"[{section}] collected {len(out_ids)} unique ids from {total} page(s)")
    return out_ids


# --------------------------------------------------------------------------- #
# Downloading (stateless, rate-limited, parallel)
# --------------------------------------------------------------------------- #
_thread_local = threading.local()


def http() -> requests.Session:
    """One pooled requests.Session per download thread."""
    sess = getattr(_thread_local, "sess", None)
    if sess is None:
        sess = requests.Session()
        sess.headers.update({"User-Agent": UA})
        adapter = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=8)
        sess.mount("https://", adapter)
        _thread_local.sess = sess
    return sess


def download_one(task_id: str, folder: Path, limiter: RateLimiter) -> str:
    """Download one PDF -> ``<folder>/<id>.pdf``. Returns 'ok' | 'skip' | 'fail'.

    429s are retried (with the limiter throttling down) up to ~15 attempts so a
    valid id is never lost to throttling; a genuine non-PDF response gives up fast.
    """
    dest = folder / f"{task_id}.pdf"
    if dest.exists() and dest.stat().st_size > 1000:   # already have a real file
        return "skip"
    url = PDF_URL.format(id=task_id)
    errors = 0        # connection errors / non-PDF responses -> give up fast
    throttles = 0     # 429s -> tolerate many (they clear once the pool pauses)
    while errors < 3 and throttles < 25:
        limiter.acquire()
        try:
            r = http().get(url, timeout=60)
        except Exception:
            errors += 1
            time.sleep(1.0 + errors * 0.5)
            continue
        if r.status_code == 200 and r.content[:5] == b"%PDF-":
            tmp = dest.with_suffix(".pdf.part")
            tmp.write_bytes(r.content)
            os.replace(tmp, dest)               # atomic publish
            limiter.reward()
            return "ok"
        if r.status_code == 429:
            throttles += 1
            limiter.penalize()          # pauses the whole pool; next acquire() blocks
            continue
        errors += 1                             # 404 / 500 / HTML "no report"
        time.sleep(1.0)
    return "fail"


def download_all(section, ids, folder, workers, limiter, fail_log) -> dict:
    """Download every id in parallel; live progress (with current rate) + fail log."""
    folder.mkdir(parents=True, exist_ok=True)
    ids = sorted(ids)
    total = len(ids)
    existing = sum(1 for i in ids if (folder / f"{i}.pdf").exists())
    log(f"[{section}][download] {total} PDFs -> {folder}  ({existing} already present)")

    counts = {"ok": 0, "skip": 0, "fail": 0}
    fails: list[str] = []
    lock = threading.Lock()
    start = time.time()

    def task(task_id):
        result = download_one(task_id, folder, limiter)
        with lock:
            counts[result] += 1
            if result == "fail":
                fails.append(task_id)
            done = counts["ok"] + counts["skip"] + counts["fail"]
            if done % 50 == 0 or done == total:
                rate = done / max(1e-9, time.time() - start)
                log(f"[{section}][download] {done}/{total} "
                    f"ok={counts['ok']} skip={counts['skip']} fail={counts['fail']} "
                    f"({100 * done // total}%, {rate:.1f}/s done, "
                    f"limit~{limiter.current_rate:.1f}/s)")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(task, ids))

    if fails:
        fail_log.write_text("\n".join(fails))
        log(f"[{section}] {len(fails)} failures logged to {fail_log.name}")
    on_disk = len(list(folder.glob("*.pdf")))
    log(f"[{section}] DONE  ok={counts['ok']} skip={counts['skip']} "
        f"fail={counts['fail']}  |  {on_disk} PDFs on disk")
    return counts


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def run_section(section, pdf_root, args, limiter) -> None:
    cfg = SECTIONS[section]
    folder = pdf_root / cfg["folder"]
    log(f"===== {section}  ->  {folder} =====")

    ids = collect_ids(section, args.collect_workers, args.page_delay, args.max_pages)
    if args.limit and len(ids) > args.limit:
        ids = set(sorted(ids)[: args.limit])
        log(f"[{section}] limited to {len(ids)} ids for this run")
    if not ids:
        log(f"[{section}] no ids collected -- skipping download")
        return
    if args.collect_only:
        log(f"[{section}] --collect-only: {len(ids)} ids, no downloads")
        return

    time.sleep(5)   # let the server's rate window drain between Selenium paging and downloads
    fail_log = pdf_root / f"{cfg['folder']}__failures.txt"
    download_all(section, ids, folder, args.download_workers, limiter, fail_log)


def main() -> None:
    ap = argparse.ArgumentParser(description="Scrape all NASA Task Book PDFs into the PDF library.")
    ap.add_argument("--section", choices=["taskbook", "bibliography", "both"], default="both")
    ap.add_argument("--collect-workers", type=int, default=3,
                    help="parallel headless browsers used to scrape result pages")
    ap.add_argument("--download-workers", type=int, default=4,
                    help="parallel PDF download threads (throughput is capped by --rate)")
    ap.add_argument("--rate", type=float, default=1.5,
                    help="starting target request rate (req/s) for the adaptive limiter")
    ap.add_argument("--max-rate", type=float, default=2.5,
                    help="ceiling the limiter may recover to after sustained success")
    ap.add_argument("--penalty", type=float, default=360.0,
                    help="seconds to pause the whole pool after a 429; MUST exceed the server's "
                         "block window (~300s observed) or the pause-resume cycle never clears it")
    ap.add_argument("--page-delay", type=float, default=0.5,
                    help="pause between result-page loads during collection (s)")
    ap.add_argument("--max-pages", type=int, default=0,
                    help="cap result pages scraped per section (smoke testing)")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap number of PDFs downloaded per section (smoke testing)")
    ap.add_argument("--collect-only", action="store_true",
                    help="scrape and count ids, download nothing")
    args = ap.parse_args()

    pdf_root = find_pdf_root(Path(__file__).resolve().parent)
    log(f"PDF library root: {pdf_root}")
    log(f"limiter: start {args.rate}/s, ceiling {args.max_rate}/s, "
        f"{args.penalty}s pause on 429, {args.download_workers} workers")
    limiter = RateLimiter(args.rate, args.max_rate, penalty=args.penalty)
    sections = ["taskbook", "bibliography"] if args.section == "both" else [args.section]

    t0 = time.time()
    for section in sections:
        run_section(section, pdf_root, args, limiter)
    log(f"All done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
