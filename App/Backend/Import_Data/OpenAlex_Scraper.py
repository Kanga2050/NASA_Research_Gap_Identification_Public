import os

import requests
import pandas as pd
import time
from pathlib import Path

from Backend.backend_utils import progress_line
from Servers.storage_paths import resolve_csv_path

def openalex_scraper(topic, csv_name="scraped", limit = 10000, csv_root: str | Path | None = None):
    """Fetch up to `limit` works matching `topic` (that have an abstract) from the
    OpenAlex API into a brand new CSV. Rows are streamed to disk in pages of 200 as
    they arrive, so partial progress survives an interruption."""
    headers = {
        'User-Agent': 'shauryachauhan2050@gmail.com'
    }

    base_url = "https://api.openalex.org/works"

    params = {
        'search': topic,
        'filter': "has_abstract:true",
        'per_page': 200,
        'cursor': '*',
    }
    # Premium OpenAlex accounts get a higher rate limit via an API key; anonymous
    # (or "polite pool") requests work fine without one.
    api_key = os.environ.get("OPENALEX_API_KEY")
    if api_key:
        params['api_key'] = api_key

    # The abstract text lands in a `text` column (the canonical raw-text column
    # name shared with the PDF corpora, so combine_csvs unions them cleanly).
    columns = [
        'openalex_id', 'title', 'doi', 'text', 'publish_time',
        'authors', 'journal', 'pmcid', 'pubmed_id'
    ]

    output_filename = resolve_csv_path(csv_name, csv_root)
    pd.DataFrame(columns = columns).to_csv(output_filename, index=False)
    print(f"Searching OpenAlex for '{topic}' (abstracts only); target up to {limit:,} papers → '{csv_name}.csv'.")
    total_collected = 0

    while params['cursor'] and total_collected < limit:
        try:
            print(progress_line(f"Downloading '{topic}' papers", total_collected, limit))
            response = requests.get(base_url, params = params, headers = headers)
            response.raise_for_status()
            data = response.json()

            results = data.get('results', [])
            if not results:
                print(f"OpenAlex returned no more results; stopping at {total_collected:,} papers.")
                break
            
            batch_data = []

            for paper in results:
                abstract_index = paper.get('abstract_inverted_index', {})
                abstract = ""
                if abstract_index:
                    words = []
                    for word, positions in abstract_index.items():
                        for pos in positions:
                            words.append((pos, word))
                    words.sort()
                    abstract = ' '.join([word for _, word in words])
            
                if not abstract.strip():
                    continue
                
                authors = [auth.get('author', {}).get('display_name', '')
                           for auth in paper.get('authorships', [])]
                authors = [name for name in authors if name]

                journal = ''
                primary_location = paper.get('primary_location')
                if primary_location and primary_location.get('source'):
                    journal = primary_location['source'].get('display_name', '')

                batch_data.append({
                    'openalex_id': paper.get('id', ''),
                    'title': paper.get('title', ''),
                    'doi': paper.get('doi', ''),
                    'text': abstract,
                    'publish_time': paper.get('publication_date', ''),
                    'authors': '; '.join(authors),
                        'journal': journal,
                    'pmcid': paper.get('ids', {}).get('pmcid', ''),
                    'pubmed_id': paper.get('ids', {}).get('pmid', '')
                })

                total_collected += 1
                if total_collected >= limit:
                    break
        
            if batch_data:
                batch_df = pd.DataFrame(batch_data, columns = columns)
                batch_df.to_csv(output_filename, mode='a', header=False, index=False)
        
            params['cursor'] = data.get('meta', {}).get('next_cursor')
            time.sleep(0.1)

        except Exception as e:
            print(f"Stopped early after an error ({e}); {total_collected:,} papers already saved.")
            break

    print(progress_line(f"Downloading '{topic}' papers", total_collected, min(limit, max(total_collected, 1))))
    print(f"Success! Saved {total_collected:,} '{topic}' papers (with abstracts) to new file '{csv_name}.csv'.")


if __name__ == "__main__":
    openalex_scraper(
        topic = "Space Biology",
        csv_name = "Space_Biology",
        limit = 100000
    )