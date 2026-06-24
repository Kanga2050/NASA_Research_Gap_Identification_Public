import time
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

def setup_driver():
    """Initializes a headless Chrome browser."""
    chrome_options = Options()
    #chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def clean_and_extract_all(soup):
    """Removes junk HTML layout tags and extracts all readable text."""
    for element in soup(["script", "style", "nav", "footer", "header", "noscript", "meta"]):
        element.decompose()
    page_text = soup.get_text(separator="\n")
    # Clean up excessive empty lines while preserving structural spacing
    return "\n".join([line.strip() for line in page_text.splitlines() if line.strip()])

def crawl_page_selenium(driver, url, current_depth, max_depth, visited_urls):
    """Recursively processes pages, printing all text and links found."""
    if current_depth > max_depth or url in visited_urls:
        return

    visited_urls.add(url)
    
    # Visual dividers to clearly separate pages in the console output
    print("\n" + "#" * 80)
    print(f"➔ [DEPTH {current_depth}] CRAWLING PAGE: {url}")
    print("#" * 80)

    try:
        driver.get(url)
        time.sleep(4)  # Allow dynamic JavaScript elements to finish rendering
        
        soup = BeautifulSoup(driver.page_source, "html.parser")

        # 1. Gather all links on the current page first
        found_links = []
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            absolute_url = urljoin(url, href)
            clean_url = absolute_url.split("#")[0]  # Strip anchors

            if clean_url.startswith("http"):
                found_links.append(clean_url)

        unique_found_links = list(dict.fromkeys(found_links))

        # 2. Print ALL Extracted Text
        all_text = clean_and_extract_all(soup)
        print("\n--- ALL EXTRACTED TEXT ---")
        if all_text:
            print(all_text)
        else:
            print("[No readable text found on this page]")

        # 3. Print ALL Discovered Links
        print("\n--- ALL LINKS FOUND ON PAGE ---")
        if unique_found_links:
            for l in unique_found_links:
                print(f"- {l}")
        else:
            print("[No links found on this page]")

        print("\n" + "-" * 80)

        # 4. Move down recursively into the discovered links
        for next_url in unique_found_links:
            crawl_page_selenium(driver, next_url, current_depth + 1, max_depth, visited_urls)

    except Exception as e:
        print(f"✕ Selenium failed to load {url}: {e}")

def start_selenium_crawler(start_url, max_depth=1):
    """Manages the driver lifecycle and initiates the complete print loop."""
    print(f"Starting Selenium complete crawl at: {start_url}")
    print(f"Max Depth Limit: {max_depth}")
    
    driver = setup_driver()
    visited_set = set()
    try:
        crawl_page_selenium(driver, start_url, current_depth=0, max_depth=max_depth, visited_urls=visited_set)
    finally:
        print("\n" + "=" * 80)
        print(f"Crawl finished. Disconnected browser window safely.")
        print(f"Total unique pages fully printed: {len(visited_set)}")
        print("=" * 80)
        driver.quit()

if __name__ == "__main__":
    # The starting link
    target_link = "https://techport.nasa.gov/collaborators"
    
    # Depth 0 = prints only the target link data
    # Depth 1 = prints target link data + loops through and prints every sub-link found
    recursion_depth = 2
    
    start_selenium_crawler(target_link, max_depth=recursion_depth)
