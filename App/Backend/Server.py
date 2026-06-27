import sys
import os
import uuid
import pandas
from typing import Dict, Any, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastmcp import FastMCP

# Add local paths to path resolution for safety
sys.path.append(os.path.join(os.getcwd(), 'Annotation_Functions'))
sys.path.append(os.path.join(os.getcwd(), 'Visualization_Functions'))

# Import all modules from your pipeline
from Annotation_Functions.Embedder import add_embeddings_in_place
from Annotation_Functions.Dimensionality_Reducer import reduce_embeddings_with_umap
from Annotation_Functions.Clustering import cluster_with_hdbscan
from Visualization_Functions.Distance_Map import generate_intertopic_distance_map
from Annotation_Functions.Keyword_Score import keyword_search
from Annotation_Functions.Semantic_Score import semantic_search
from Annotation_Functions.Hybrid_Score import hybrid_search
from Distillation_Functions.Numerical_Filtering import numerical_search

# 1. Initialize core FastAPI context
app = FastAPI(title="Deconstructed Pipeline API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared memory tracking log for background pipeline jobs
task_registry: Dict[str, Any] = {}

# 2. Async Engine Executor Thread Helper
def run_async_step(task_id: str, function_name: str, func, *args, **kwargs):
    """Executes any pipeline step on a background thread and caches execution state."""
    try:
        task_registry[task_id] = {"function": function_name, "status": "processing"}
        print(f"[Engine] Running task {task_id} ({function_name})...")
        
        # Invoke your pipeline module dynamically
        func(*args, **kwargs)
        
        task_registry[task_id]["status"] = "completed"
        task_registry[task_id]["result"] = f"Function '{function_name}' executed successfully."
    except Exception as e:
        task_registry[task_id]["status"] = "failed"
        task_registry[task_id]["error"] = str(e)


# --- 3. GLOBAL STATUS TRACKER ---
@app.get("/api/task/status/{task_id}")
def get_task_status(task_id: str):
    """Exposed endpoint to check up on background thread execution updates."""
    if task_id not in task_registry:
        raise HTTPException(status_code=404, detail="Task ID not registered.")
    return task_registry[task_id]


# --- 4. DECONSTRUCTED ROUTE HANDLERS ---

# ----------------- STEP A: EMBEDDING GENERATION -----------------
class EmbedRequest(BaseModel):
    file_path: str
    text_column: str = "abstract"
    embedding_column: str = "abstract_embedding"
    model: str = "allenai/specter2_base"

@app.post("/api/pipeline/embed")
def trigger_embed(data: EmbedRequest, bg_tasks: BackgroundTasks) -> Dict[str, str]:
    """Generates vector embeddings across targeted textual rows."""
    task_id = str(uuid.uuid4())
    bg_tasks.add_task(
        run_async_step, task_id, "add_embeddings_in_place", 
        add_embeddings_in_place, data.file_path, data.text_column, data.embedding_column, data.model
    )
    return {"task_id": task_id, "status": "queued"}


# ----------------- STEP B: UMAP REDUCTION -----------------
class UmapRequest(BaseModel):
    file_path: str
    embedding_column: str = "abstract_embedding"
    output_column: str
    n_components: int

@app.post("/api/pipeline/umap")
def trigger_umap(data: UmapRequest, bg_tasks: BackgroundTasks) -> Dict[str, str]:
    """Applies dimensional reduction coordinates to a targets coordinate array space."""
    task_id = str(uuid.uuid4())
    bg_tasks.add_task(
        run_async_step, task_id, "reduce_embeddings_with_umap",
        reduce_embeddings_with_umap, data.file_path, data.embedding_column, data.output_column, n_components=data.n_components
    )
    return {"task_id": task_id, "status": "queued"}


# ----------------- STEP C: HDBSCAN CLUSTERING -----------------
class ClusterRequest(BaseModel):
    file_path: str
    coordinate_column: str = "5d"
    output_column: str = "topic_id"
    min_cluster_size: int = 32
    min_samples: int = 8

@app.post("/api/pipeline/cluster")
def trigger_cluster(data: ClusterRequest, bg_tasks: BackgroundTasks) -> Dict[str, str]:
    """Processes computational geometric classification steps through spatial density mappings."""
    task_id = str(uuid.uuid4())
    bg_tasks.add_task(
        run_async_step, task_id, "cluster_with_hdbscan",
        cluster_with_hdbscan, data.file_path, data.coordinate_column, data.output_column, data.min_cluster_size, data.min_samples
    )
    return {"task_id": task_id, "status": "queued"}


# ----------------- STEP D: INTERTOPIC DISTANCE MAPS -----------------
class DistanceMapRequest(BaseModel):
    file_path: str
    topic_column: str = "topic_id"
    text_column: str = "abstract"
    coordinate_column: str = "2d"

@app.post("/api/pipeline/distance-map")
def trigger_distance_map(data: DistanceMapRequest, bg_tasks: BackgroundTasks) -> Dict[str, str]:
    """Builds topological representations mapping the contextual vector distances of structural topics."""
    task_id = str(uuid.uuid4())
    bg_tasks.add_task(
        run_async_step, task_id, "generate_intertopic_distance_map",
        generate_intertopic_distance_map, data.file_path, data.topic_column, data.text_column, data.coordinate_column
    )
    return {"task_id": task_id, "status": "queued"}


# ----------------- STEP E: KEYWORD SEARCH SEEDING -----------------
class KeywordSearchRequest(BaseModel):
    file_path: str
    query: str
    text_column: str = "abstract"
    new_column_name: str = "kw"

@app.post("/api/pipeline/keyword-search")
def trigger_keyword_search(data: KeywordSearchRequest, bg_tasks: BackgroundTasks) -> Dict[str, str]:
    """Executes frequency-based lexical matches matching precise string parameter strings."""
    task_id = str(uuid.uuid4())
    bg_tasks.add_task(
        run_async_step, task_id, "keyword_search",
        keyword_search, data.file_path, data.query, data.text_column, data.new_column_name
    )
    return {"task_id": task_id, "status": "queued"}


# ----------------- STEP F: SEMANTIC SEARCH METRICS -----------------
class SemanticSearchRequest(BaseModel):
    file_path: str
    query: str
    embedding_column: str = "abstract_embedding"
    new_column_name: str = "sem"

@app.post("/api/pipeline/semantic-search")
def trigger_semantic_search(data: SemanticSearchRequest, bg_tasks: BackgroundTasks) -> Dict[str, str]:
    """Determines high-dimensional cosine similarity matrix associations across vector spaces."""
    task_id = str(uuid.uuid4())
    bg_tasks.add_task(
        run_async_step, task_id, "semantic_search",
        semantic_search, data.file_path, data.query, data.embedding_column, data.new_column_name
    )
    return {"task_id": task_id, "status": "queued"}


# ----------------- STEP G: HYBRID WEIGHTED SEARCH -----------------
class HybridSearchRequest(BaseModel):
    file_path: str
    keyword_col: str = "kw"
    semantic_col: str = "sem"
    new_column_name: str = "hybrid"

@app.post("/api/pipeline/hybrid-search")
def trigger_hybrid_search(data: HybridSearchRequest, bg_tasks: BackgroundTasks) -> Dict[str, str]:
    """Combines lexical keyword matching scores and dense vector semantic context mappings."""
    task_id = str(uuid.uuid4())
    bg_tasks.add_task(
        run_async_step, task_id, "hybrid_search",
        hybrid_search, data.file_path, data.keyword_col, data.semantic_col, data.new_column_name
    )
    return {"task_id": task_id, "status": "queued"}


# ----------------- STEP H: NUMERICAL SCORE DISTILLATION -----------------
class NumericalSearchRequest(BaseModel):
    file_path: str
    output_csv: str = "Filtered_Output.csv"
    target_score_column: str = "hybrid"
    threshold: float = 0.70

@app.post("/api/pipeline/numerical-distillation")
def trigger_numerical_search(data: NumericalSearchRequest, bg_tasks: BackgroundTasks) -> Dict[str, str]:
    """Performs downstream structural rows pruning using explicit cutoff conditions."""
    task_id = str(uuid.uuid4())
    bg_tasks.add_task(
        run_async_step, task_id, "numerical_search",
        numerical_search, data.file_path, data.output_csv, data.target_score_column, data.threshold
    )
    return {"task_id": task_id, "status": "queued"}


mcp = FastMCP.from_fastapi(app)

DATA_DIR = "./App/Backend/CSVs"

@mcp.resource("csv://catalog")
def get_csv_catalog() -> str:
    """
    Returns a list of all CSVs in the data folder, their exact column names, 
    and their approximate size in rows and megabytes.
    """
    catalog_info = ["# CSV Data Catalog\n"]
    
    if not os.path.exists(DATA_DIR):
        return f"Error: Data directory '{DATA_DIR}' not found."

    for file in os.listdir(DATA_DIR):
        if file.endswith(".csv"):
            path = os.path.join(DATA_DIR, file)
            size_mb = os.path.getsize(path) / (1024 * 1024)
            
            # Read only the header to extract column labels (zero memory cost)
            try:
                df_header = pandas.read_csv(path, nrows=0)
                columns = list(df_header.columns)
                
                # Fast row count (generator expression avoids loading file into RAM)
                with open(path, 'rb') as f:
                    row_count = sum(1 for _ in f) - 1 # Subtract 1 for header
                
                catalog_info.append(f"### {file}")
                catalog_info.append(f"- **Size:** {size_mb:.2f} MB ({row_count} rows)")
                catalog_info.append(f"- **Columns:** {', '.join(columns)}\n")
            except Exception as e:
                catalog_info.append(f"### {file}\n- **Error reading file:** {str(e)}\n")

    return "\n".join(catalog_info)


@mcp.resource("csv://{filename}/segment/{start_row}/{num_rows}/{columns}")
def get_csv_segment(filename: str, start_row: int, num_rows: int, columns: str) -> str:
    """
    Retrieves a specific segment of a CSV.
    - filename: The name of the csv file (e.g., 'data.csv')
    - start_row: The index of the first row to read (0-indexed)
    - num_rows: How many rows to return
    - columns: Comma-separated list of columns, or 'all' for all columns
    """
    path = os.path.join(DATA_DIR, filename)
    
    if not os.path.exists(path):
        return f"Error: File '{filename}' not found."

    # Parse requested columns
    usecols = None # Pandas uses None to mean "all columns"
    if columns.lower() != "all":
        usecols = [col.strip() for col in columns.split(",")]

    try:
        # skiprows=range(1, start_row + 1) safely skips past rows we don't want,
        # while implicitly keeping row 0 (the header row).
        # usecols ensures pandas DOES NOT even parse the columns we don't request.
        df = pandas.read_csv(
            path,
            skiprows=range(1, start_row + 1),
            nrows=num_rows,
            usecols=usecols
        )
        
        if df.empty:
            return "No data found at this row segment (End of file reached)."

        # Optional: Truncate massively long text fields to protect the LLM context window
        for col in df.columns:
            if df[col].dtype == object: # usually strings
                df[col] = df[col].astype(str).apply(
                    lambda x: x[:30] + "... [truncated]" if len(x) > 30 else x
                )

        return df.to_markdown(index=False)
        
    except ValueError as e:
        return f"Column Error: Make sure the columns requested exist. Details: {str(e)}"
    except Exception as e:
        return f"Error reading segment: {str(e)}"




mcp_app = mcp.http_app()


combined_app = FastAPI(
    title="Deconstructed Pipeline API (With MCP Integration)",
    description="Atomic Data Science execution blocks serving Frontend and AI Agents.",
    lifespan=mcp_app.lifespan,  # <--- THIS IS THE MAGIC LINE FIXING THE 500 ERROR
    routes=[
        *mcp_app.routes,
        *app.routes,
    ]
)

if __name__ == "__main__":
    import uvicorn
    # Run the new combined_app
    uvicorn.run(combined_app, host="127.0.0.1", port=8000)