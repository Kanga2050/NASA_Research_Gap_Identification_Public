import sys
import os
import uuid
import threading
from fastmcp import FastMCP
from fastmcp.apps import AppConfig  

current_dir = os.path.dirname(os.path.abspath(__file__))
target_path = os.path.abspath(os.path.join(current_dir, ".."))
if target_path not in sys.path:
    sys.path.append(target_path)

from task_manager import shared_task_registry, add_task_to_queue, get_iso_time

from Backend.Annotation_Functions.Embed_Text import embed_text as _embed_text
from Backend.Annotation_Functions.Reduce_Dimensionality import reduce_dimensionality as _reduce_dimensionality
from Backend.Annotation_Functions.Cluster import cluster as _cluster
from Backend.Visualization_Functions.Distance_Map import distance_map as _distance_map
from Backend.Annotation_Functions.Keyword_Score import keyword_score as _keyword_score
from Backend.Annotation_Functions.Semantic_Score import semantic_score as _semantic_score
from Backend.Annotation_Functions.Hybrid_Score import hybrid_score as _hybrid_score
from Backend.Distillation_Functions.Numerical_Filter import numerical_filter as _numerical_filter
from Servers.Getter_Functions.List_Html_Files import list_html_files as _list_html_files
from Servers.Getter_Functions.Get_Csv_Catalog import get_csv_catalog as _get_csv_catalog
from Servers.Getter_Functions.Get_Csv_Segment import get_csv_segment as _get_csv_segment
from Backend.Import_Data.OpenAlex_Scraper import openalex_scraper as _openalex_scraper

# Initialize the MCP Server
mcp = FastMCP("NLP Analysis Platform")

def queue_mcp_task(func_name: str, func, *args, **kwargs) -> dict:
    """
    Replaces FastAPI's BackgroundTasks by spinning up a lightweight 
    background thread to pass the task into the sequential queue.
    """
    task_id = str(uuid.uuid4())
    now = get_iso_time()
    shared_task_registry[task_id] = {"status": "queued", "createdAt": now, "lastUpdatedAt": now}
    
    threading.Thread(
        target=add_task_to_queue, 
        args=(task_id, func_name, func, *args), 
        kwargs=kwargs,
        daemon=True
    ).start()
    
    return {"task_id": task_id, "status": "queued"}



@mcp.tool()
def get_task_status(task_id: str):
    """
    Check the current status of any pipeline task by its task_id.

    Call this after calling any queued tool (embed_text, cluster, reduce_dimensionality,
    keyword_score, semantic_score, hybrid_score, numerical_filter, distance_map,
    openalex_scraper) to find out whether it has finished. All of those tools return
    immediately with a task_id — they do not block. You must poll this tool to know
    when the work is actually done before calling the next step.

    Status values you will see:
      "queued"     — the task is waiting in the sequential execution queue
      "processing" — the task is actively running right now
      "completed"  — the task finished successfully; safe to call the next pipeline step
      "failed"     — the task encountered an error; check the "error" field for details

    Args:
        task_id: The UUID string returned by any queued pipeline tool.

    Returns:
        A dict with keys: status, createdAt, lastUpdatedAt, and optionally error.
        Example: {"status": "completed", "createdAt": "...", "lastUpdatedAt": "..."}
    """
    if task_id not in shared_task_registry:
        return {"error": "Task not found."}
    return shared_task_registry[task_id]

@mcp.tool()
def get_task_history(limit: int = 20) -> list:
    """
    Returns a list of recent pipeline task runs, sorted newest first.

    Call this at the start of a session to understand what has already been run
    on the dataset — for example, to check whether embeddings have already been
    generated, or whether clustering has completed. This avoids re-running
    expensive steps (like embed_text, which downloads a 440MB model and processes
    every row) unnecessarily.

    Also useful after a failure: if you are not sure which step failed or succeeded,
    get_task_history gives you the full picture across all recent operations.

    Args:
        limit: Maximum number of recent tasks to return. Defaults to 20.
               Increase this if you need to look further back in history.

    Returns:
        A list of task dicts, each containing:
          task_id, status ("queued"/"processing"/"completed"/"failed"),
          createdAt, lastUpdatedAt, and optionally an error message.
        Sorted newest first so the most recent operation is always at index 0.
    """
    items = list(shared_task_registry.items())
    # Sort by createdAt descending so newest tasks come first
    items.sort(key=lambda kv: kv[1].get("createdAt", ""), reverse=True)
    return [{"task_id": k, **v} for k, v in items[:limit]]

@mcp.tool()
def get_csv_catalog():
    """
    List all available CSV files in the data directory, with their column names,
    row counts, and file sizes.

    Always call this first at the start of a new analysis session. It tells you:
      - Which datasets are available (e.g. "Space_Biology.csv")
      - What columns each dataset has — critical for knowing whether embed_text
        has already been run (look for "abstract_embedding"), whether clustering
        is done (look for "topic_id"), and which score columns exist ("kw", "sem",
        "hybrid") from previous search runs
      - How large each dataset is, so you can set appropriate parameters
        (e.g. min_cluster_size for HDBSCAN clustering)

    No arguments needed. Returns a structured catalog string.

    Typical workflow: call get_csv_catalog → inspect columns → decide which
    pipeline steps still need to run based on what columns already exist.
    """
    return _get_csv_catalog()

@mcp.tool()
def list_html_files():
    """
    List all HTML visualization files that have been generated and are available
    to display.

    Call this to discover what visualizations currently exist before calling
    display_html_file. Visualization files are generated by the distance_map tool,
    which produces interactive intertopic distance maps and other cluster
    visualizations as standalone HTML files.

    Returns a list of filenames. Pass any filename from this list directly to
    display_html_file to render it in the UI.

    If this returns an empty list, no visualizations have been generated yet.
    You must complete the full pipeline first:
    embed_text → reduce_dimensionality (5d) → cluster → distance_map
    before any HTML files will appear here.
    """
    return _list_html_files()

@mcp.tool()
def get_csv_segment(csv_name: str, start_row: int, num_rows: int, columns: str):
    """
    Retrieve a specific slice of rows and columns from a CSV file for inspection.

    Use this to examine the actual data at any point in the pipeline — for example,
    to check what the abstract text looks like before embedding, to verify that
    score columns were written correctly after keyword_score or semantic_score,
    or to inspect which topic_id values were assigned after clustering.

    This tool reads directly from disk without loading the full file into memory,
    so it is safe to use on large datasets.

    Args:
        csv_name:  Filename of the CSV (e.g. "Space_Biology.csv"). Do not include
                   the full path — just the filename.
        start_row: Zero-indexed row number to start reading from. Use 0 for the
                   beginning of the file.
        num_rows:  How many rows to return. Keep this small (10-50) for inspection;
                   large values may return too much text for the context window.
        columns:   Comma-separated list of column names to include, e.g.
                   "title,abstract,topic_id" — or pass "all" to get every column.
                   Prefer specifying only the columns you need; embedding columns
                   contain very long strings that waste context.

    Returns:
        A markdown-formatted table of the requested rows and columns.
        Long text fields are automatically truncated at 30 characters to keep
        the output readable.
    """
    return _get_csv_segment(csv_name, start_row, num_rows, columns)



@mcp.tool(name="embed_text")
def embed_text(csv_name: str, text_column: str = "abstract", embedding_column: str = "abstract_embedding", model: str = "allenai/specter2_base") -> dict:
    """
    Generate vector embeddings for a text column in a CSV and store them in a
    new column. This is STEP 1 of the analysis pipeline and must be completed
    before reduce_dimensionality, semantic_score, or query_search can be called.

    Embeddings are numerical representations of text that capture semantic meaning.
    Two abstracts about similar topics will have similar embedding vectors, even if
    they use completely different words. This is what enables semantic search and
    topic clustering downstream.

    This tool queues a background task and returns a task_id immediately. The
    actual embedding process takes several minutes on a large dataset (a 440MB
    transformer model processes every row in batches). Poll get_task_status with
    the returned task_id until status is "completed" before proceeding.

    Before calling: verify via get_csv_catalog that the target CSV exists and
    contains the text column you want to embed. If "abstract_embedding" already
    appears in the column list, this step has already been done — skip it.

    Args:
        csv_name:         Filename of the CSV to embed (e.g. "Space_Biology.csv").
        text_column:      Name of the column containing the text to embed.
                          Defaults to "abstract".
        embedding_column: Name of the new column to write embeddings into.
                          Defaults to "abstract_embedding".
        model:            HuggingFace model ID to use for embedding. Defaults to
                          "allenai/specter2_base", which is optimized for scientific
                          literature. Do not change this unless you know the dataset
                          was embedded with a different model.

    Returns:
        {"task_id": str, "status": "queued"} — poll get_task_status to track progress.

    Pipeline position: START → embed_text → reduce_dimensionality → cluster → ...
    """
    return queue_mcp_task("embed_text", _embed_text, csv_name, text_column, embedding_column, model)

@mcp.tool(name="reduce_dimensionality")
def reduce_dimensionality(csv_name: str, output_column: str, n_components: int, embedding_column: str = "abstract_embedding") -> dict:
    """
    Reduce high-dimensional embeddings to a lower-dimensional coordinate space
    using UMAP. Must be called AFTER embed_text has completed.

    Embeddings from specter2_base are 768-dimensional vectors — too many dimensions
    for HDBSCAN clustering to work well (the "curse of dimensionality"). This step
    compresses them into a smaller coordinate space while preserving the relative
    distances between similar papers.

    You typically need to run this TWICE on the same dataset:
      1. n_components=5, output_column="5d" — for clustering (HDBSCAN works best
         on 5-10 dimensions rather than 2, where too much structure is lost)
      2. n_components=2, output_column="2d" — for visualization (the distance_map
         tool needs 2D coordinates to plot topic positions on a 2D canvas)

    This tool queues a background task. Poll get_task_status until "completed"
    before calling cluster (which needs "5d") or distance_map (which needs "2d").

    Args:
        csv_name:         Filename of the CSV (e.g. "Space_Biology.csv").
        output_column:    Name of the new column to write coordinates into.
                          Use "5d" for clustering, "2d" for visualization.
        n_components:     Target number of dimensions. Use 5 for clustering,
                          2 for visualization.
        embedding_column: Source column containing the raw embeddings.
                          Defaults to "abstract_embedding".

    Returns:
        {"task_id": str, "status": "queued"} — poll get_task_status to track progress.

    Pipeline position: embed_text → reduce_dimensionality → cluster → distance_map
    """
    return queue_mcp_task("reduce_dimensionality", _reduce_dimensionality, csv_name, embedding_column, output_column, n_components=n_components)

@mcp.tool(name="cluster")
def cluster(csv_name: str, coordinate_column: str = "5d", output_column: str = "topic_id", min_cluster_size: int = 32, min_samples: int = 8) -> dict:
    """
    Group papers into topic clusters using HDBSCAN density-based clustering.
    Must be called AFTER reduce_dimensionality with n_components=5 ("5d") has
    completed.

    HDBSCAN finds natural groupings in the embedding space without requiring
    you to specify the number of clusters in advance. Papers that are semantically
    similar end up in the same cluster. Papers that do not fit any dense group
    are labeled as noise (topic_id = -1).

    The resulting topic_id column is the foundation for research gap identification:
    small, isolated clusters represent niche topics, and gaps between large clusters
    in the distance map represent areas with little published research.

    This tool queues a background task. Poll get_task_status until "completed"
    before calling distance_map (which needs the topic_id column to exist).

    Args:
        csv_name:          Filename of the CSV (e.g. "Space_Biology.csv").
        coordinate_column: Column containing the reduced coordinates to cluster on.
                           Must be "5d" (generated by reduce_dimensionality with
                           n_components=5). Do not cluster on raw embeddings.
        output_column:     Name of the new column to write topic IDs into.
                           Defaults to "topic_id".
        min_cluster_size:  Minimum number of papers required to form a valid topic.
                           Defaults to 32. Lower this (e.g. 10-15) if your dataset
                           is small or you want to detect niche sub-topics. Raise
                           it (e.g. 50-100) for larger datasets to avoid noise.
        min_samples:       Controls how conservative the cluster boundaries are.
                           Higher values mean more papers get labeled as noise (-1)
                           but the clusters that form are more cohesive. Defaults to 8.

    Returns:
        {"task_id": str, "status": "queued"} — poll get_task_status to track progress.

    Pipeline position: reduce_dimensionality → cluster → distance_map
    """
    return queue_mcp_task("cluster", _cluster, csv_name, coordinate_column, output_column, min_cluster_size, min_samples)

@mcp.tool(name="distance_map")
def distance_map(csv_name: str, topic_column: str = "topic_id", text_column: str = "abstract", coordinate_column: str = "2d", output_name: str = "Space_Biology_Topics") -> dict:
    """
    Generate an interactive intertopic distance map visualization as a standalone
    HTML file. Must be called AFTER both cluster AND reduce_dimensionality with
    n_components=2 ("2d") have completed.

    The distance map plots each topic cluster as a circle on a 2D canvas. The
    position of each circle reflects how semantically related topics are to each
    other — closely positioned clusters share similar vocabulary and concepts,
    while distant clusters are conceptually unrelated. The size of each circle
    represents how many papers belong to that topic.

    This is one of the primary tools for identifying research gaps: large empty
    spaces between clusters on the map indicate areas that are conceptually
    "between" two studied topics but have little published research of their own.

    After this completes, call list_html_files to see the generated file, then
    display_html_file to render it in the UI.

    Args:
        csv_name:          Filename of the CSV (e.g. "Space_Biology.csv").
        topic_column:      Column containing cluster labels from the cluster step.
                           Defaults to "topic_id".
        text_column:       Column containing the original text (used to generate
                           topic labels/keywords for the map). Defaults to "abstract".
        coordinate_column: Column containing 2D coordinates from reduce_dimensionality
                           with n_components=2. Defaults to "2d".
        output_name:       Filename stem for the generated HTML file (without .html).
                           Defaults to "Space_Biology_Topics".

    Returns:
        {"task_id": str, "status": "queued"} — poll get_task_status to track progress.
        Once completed, call list_html_files and then display_html_file to view the result.

    Pipeline position: cluster + reduce_dimensionality(2d) → distance_map → display_html_file
    """
    return queue_mcp_task("distance_map", _distance_map, csv_name, topic_column, text_column, coordinate_column, output_name)

@mcp.tool(name="keyword_score")
def keyword_score(csv_name: str, query: str, text_column: str = "abstract", new_column_name: str = "kw") -> dict:
    """
    Score every paper in the CSV by lexical similarity to a query using TF-IDF
    (Term Frequency-Inverse Document Frequency). Writes a score column to the CSV.

    This is the first half of the hybrid search pipeline. TF-IDF finds papers that
    contain the same words as your query — it is fast and precise for exact
    terminology matches, but will miss papers that discuss the same concept using
    different vocabulary (e.g. "microgravity" vs "zero-g" vs "weightlessness").
    That limitation is why keyword_score is combined with semantic_score in the
    hybrid pipeline.

    Run keyword_score and semantic_score independently (they can run in parallel
    since they both only read the CSV, not write conflicting columns), then combine
    their results with hybrid_score.

    Args:
        csv_name:        Filename of the CSV (e.g. "Space_Biology.csv").
        query:           The search term or phrase to score papers against.
                         Use domain-specific terminology for best results.
        text_column:     Column containing the text to score. Defaults to "abstract".
        new_column_name: Name of the new score column to write. Defaults to "kw".
                         If you run multiple keyword searches, use distinct names
                         (e.g. "kw_bone", "kw_muscle") to avoid overwriting.

    Returns:
        {"task_id": str, "status": "queued"} — poll get_task_status to track progress.
        Once completed, a new column (default "kw") will exist in the CSV containing
        cosine similarity scores between 0 and 1 for each paper.

    Pipeline position: (embed_text) → keyword_score + semantic_score → hybrid_score → numerical_filter
    """
    return queue_mcp_task("keyword_score", _keyword_score, csv_name, query, text_column, new_column_name)

@mcp.tool(name="semantic_score")
def semantic_score(csv_name: str, query: str, embedding_column: str = "abstract_embedding", new_column_name: str = "sem") -> dict:
    """
    Score every paper in the CSV by semantic (meaning-level) similarity to a query
    using the stored embedding vectors. Writes a score column to the CSV.

    This is the second half of the hybrid search pipeline. Unlike keyword_score,
    semantic scoring finds papers that discuss the same *concept* as your query
    even when they use completely different words — because both are compared as
    vectors in the same embedding space. This catches synonyms, related concepts,
    and paraphrased ideas that keyword matching would miss entirely.

    Requires embed_text to have already completed (the embedding_column must exist).
    Can run in parallel with keyword_score since they write to different columns.

    Args:
        csv_name:         Filename of the CSV (e.g. "Space_Biology.csv").
        query:            Natural-language query to find semantically similar papers.
                          Can be a full sentence or research question, not just keywords.
        embedding_column: Column containing the stored document embeddings.
                          Defaults to "abstract_embedding". Must already exist.
        new_column_name:  Name of the new score column to write. Defaults to "sem".
                          Use distinct names if running multiple semantic searches.

    Returns:
        {"task_id": str, "status": "queued"} — poll get_task_status to track progress.
        Once completed, a new column (default "sem") will exist in the CSV with
        cosine similarity scores between 0 and 1 for each paper.

    Pipeline position: embed_text → keyword_score + semantic_score → hybrid_score → numerical_filter
    """
    return queue_mcp_task("semantic_score", _semantic_score, csv_name, query, embedding_column, new_column_name)

@mcp.tool(name="hybrid_score")
def hybrid_score(csv_name: str, keyword_col: str = "kw", semantic_col: str = "sem", new_column_name: str = "hybrid") -> dict:
    """
    Combine keyword and semantic scores into a single unified relevance score
    using Reciprocal Rank Fusion (RRF). Must be called AFTER both keyword_score
    and semantic_score have completed.

    RRF works by converting raw scores into rankings, then combining the rankings
    mathematically. This means a paper that ranks highly on both keyword AND semantic
    similarity gets a much higher hybrid score than a paper that only ranks highly
    on one — rewarding papers that are strong matches by both measures simultaneously.

    The output is normalized to a 0-1 scale to make the threshold in numerical_filter
    human-interpretable (e.g. 0.70 means "top 30% of combined relevance").

    Args:
        csv_name:        Filename of the CSV (e.g. "Space_Biology.csv").
        keyword_col:     Column containing keyword scores from keyword_score.
                         Defaults to "kw".
        semantic_col:    Column containing semantic scores from semantic_score.
                         Defaults to "sem".
        new_column_name: Name of the new combined score column. Defaults to "hybrid".

    Returns:
        {"task_id": str, "status": "queued"} — poll get_task_status to track progress.
        Once completed, a "hybrid" column exists with normalized 0-1 scores.
        Use get_csv_segment to inspect the distribution before choosing a threshold
        for numerical_filter.

    Pipeline position: keyword_score + semantic_score → hybrid_score → numerical_filter
    """
    return queue_mcp_task("hybrid_score", _hybrid_score, csv_name, keyword_col, semantic_col, new_column_name)

@mcp.tool(name="numerical_filter")
def numerical_filter(source_csv: str, output_csv: str = "Filtered_Output.csv", target_score_column: str = "hybrid", threshold: float = 0.70) -> dict:
    """
    Filter the dataset to only the papers above a relevance score threshold and
    write them to a new CSV file, sorted by score descending.

    This is the final distillation step in the search pipeline. After hybrid_score
    has produced a combined relevance score for every paper, numerical_filter
    extracts only the papers that meet or exceed your threshold — giving you a
    focused, ranked list of the most relevant research for your query.

    The output CSV is a clean, sorted subset of the original dataset — the papers
    most likely to be relevant to your research question, ready for manual review
    or further analysis.

    Choosing a threshold: 0.70 is a reasonable starting point (top ~30% of papers).
    If you get too few results, lower it (e.g. 0.50). If the results still feel
    noisy, raise it (e.g. 0.80). Use get_csv_segment on the source CSV to inspect
    the "hybrid" score distribution before committing to a threshold.

    Args:
        source_csv:           Filename of the input CSV containing the hybrid score
                              column (e.g. "Space_Biology.csv").
        output_csv:           Filename for the filtered output CSV.
                              Defaults to "Filtered_Output.csv".
        target_score_column:  Name of the score column to filter on.
                              Defaults to "hybrid".
        threshold:            Minimum score to include a paper. Papers scoring below
                              this value are excluded. Range 0.0-1.0, defaults to 0.70.

    Returns:
        {"task_id": str, "status": "queued"} — poll get_task_status to track progress.
        Once completed, a new CSV exists at output_csv containing only the top papers,
        sorted by score descending.

    Pipeline position: hybrid_score → numerical_filter → (review results)
    """
    return queue_mcp_task("numerical_filter", _numerical_filter, source_csv, output_csv, target_score_column, threshold)

@mcp.tool(name="openalex_scraper")
def openalex_scraper(topic: str, csv_name: str = "scraped", limit: int = 10000) -> dict: 
    """
    Scrape academic papers from the OpenAlex API by topic and save them to a CSV
    file. This is the DATA INGESTION step — run this first if no CSV exists yet,
    or to collect papers on a new topic.

    OpenAlex is a free, open index of academic literature covering millions of
    papers across all scientific disciplines. This tool searches by topic using
    title and abstract text matching, filters to only papers that have an abstract
    (required for meaningful embedding and search), and saves the results with
    metadata columns: openalex_id, title, doi, abstract, publish_time, authors,
    journal, pmcid, pubmed_id.

    The scraper handles pagination automatically using OpenAlex's cursor-based
    API and includes retry logic with exponential backoff to handle transient
    API timeouts, which are common on broad queries. Expect this to run for
    several minutes to hours depending on the limit.

    Once completed, call embed_text on the resulting CSV to begin the analysis
    pipeline.

    Args:
        topic:    The research topic to search for. Use specific terminology
                  (e.g. "space biology", "microgravity bone loss") rather than
                  very broad terms, which are more likely to time out on the API.
        csv_name: Filename stem for the output CSV (without .csv extension).
                  Defaults to "scraped". The file will be saved as "{csv_name}.csv"
                  in the CSVs directory.
        limit:    Maximum number of papers to collect. Defaults to 10,000.
                  OpenAlex has millions of papers; set this based on how much
                  data you want to process downstream. Larger limits take longer.

    Returns:
        {"task_id": str, "status": "queued"} — poll get_task_status to track progress.
        Once completed, call get_csv_catalog to confirm the file exists and check
        its row count before proceeding to embed_text.

    Pipeline position: START → openalex_scraper → embed_text → reduce_dimensionality → ...
    """
    return queue_mcp_task("openalex_scraper", _openalex_scraper, topic, csv_name=csv_name, limit=limit)




FOLDER = "App/Backend/Visualizations"

# 1. A static wrapper resource that loads the MCP Apps SDK
@mcp.resource("ui://viewer/app.html")
def viewer_app() -> str:
    return """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <script type="module">
        import { App } from "https://unpkg.com/@modelcontextprotocol/ext-apps@0.4.0/app-with-deps";
        const app = new App({ name: "HTML Viewer", version: "1.0.0" });
        
        // When the host pushes the tool result (the HTML string), inject it
        app.ontoolresult = ({ content }) => {
            const text = content?.find(c => c.type === 'text');
            if (text) {
                document.getElementById('container').innerHTML = text.text;
            }
        };
        await app.connect();
    </script>
</head>
<body>
    <div id="container">Loading requested file...</div>
</body>
</html>"""

@mcp.tool(app=AppConfig(resource_uri="ui://viewer/app.html"))
def display_html_file(filename: str) -> str:
    """
    Render a specific HTML visualization file in the UI panel.

    Call list_html_files first to see what files are available. Then call this
    tool with the exact filename (including .html extension) to display it.

    The primary use case is displaying the intertopic distance map generated by
    distance_map — an interactive visualization showing how topic clusters relate
    to each other spatially. This is one of the core outputs for identifying
    research gaps: large empty spaces between clusters indicate areas with little
    published research that conceptually fall "between" two active research topics.

    Args:
        filename: The exact filename to display, including the .html extension
                  (e.g. "Space_Biology_Topics.html"). Must be a file that exists
                  in the visualizations folder — use list_html_files to get valid
                  filenames. Paths outside the visualizations folder are rejected
                  for security.

    Returns:
        The raw HTML content of the file, rendered in the UI viewer panel.
        If the file is not found or the path is invalid, returns an HTML error message.
    """
    filepath = os.path.join(FOLDER, filename)
    
    # Basic directory traversal protection
    if not os.path.abspath(filepath).startswith(os.path.abspath(FOLDER)):
        return "<h1>Error: Invalid file path</h1>"
        
    if not os.path.isfile(filepath):
        return f"<h1>Error: {filename} not found</h1>"
        
    with open(filepath, "r", encoding="utf-8") as f:\
        return f.read()
    
if __name__ == "__main__":
    import uvicorn
    http_app = mcp.http_app(path="/mcp")
    uvicorn.run(http_app, host="127.0.0.1", port=8000)