import os

import requests
import pandas as pd
import time

def openalex_scraper(topic, csv_name="scaped", limit = 10000):
    headers = {
        'User-Agent': 'shauryachauhan2050@gmail.com'
    }

    base_url = "https://api.openalex.org/works"
    
    params = {
        'search': topic,
        'filter': "has_abstract:true",
        'per_page':200,
        'cursor': '*',
        'api_key': "n66C3l0O086hALzQQDEDq4"
    }

    columns = [
        'openalex_id', 'title', 'doi', 'abstract', 'publish_time',
        'authors', 'journal', 'pmcid', 'pubmed_id'
    ]

    output_filename = f"App/Backend/CSVs/{csv_name}.csv"
    pd.DataFrame(columns = columns).to_csv(output_filename, index=False)
    print(f"Initialized clean file: {output_filename}")
    total_collected = 0

    while params['cursor'] and total_collected < limit:
        try:
            print(f"Progress: Fetching next batch... Total saved so far: {total_collected} / {limit}")
            response = requests.get(base_url, params = params, headers = headers)
            response.raise_for_status()
            data = response.json()
            
            results = data.get('results', [])
            if not results:
                print("no more results available.")
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
                    'abstract': abstract,
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
            print(f"\nAn error occurred: {e}")
            break
    
    print(f"\nSuccess! Process finished. {total_collected} rows saved in total.")


if __name__ == "__main__":
    openalex_scraper(
        topic = "Space Biology",
        csv_name = "Space_Biology",
        limit = 100000
    )