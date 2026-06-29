import sys
import os
import uuid
import pandas
from typing import Dict, Any, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastmcp import FastMCP
from typing import Literal
import asyncio
from pathlib import Path

# Import all modules from your pipeline
from App.Backend.Annotation_Functions.Embedder import add_embeddings_in_place
from App.Backend.Annotation_Functions.Dimensionality_Reducer import reduce_embeddings_with_umap
from App.Backend.Annotation_Functions.Clustering import cluster_with_hdbscan
from App.Backend.Visualization_Functions.Distance_Map import generate_intertopic_distance_map
from App.Backend.Annotation_Functions.Keyword_Score import keyword_search
from App.Backend.Annotation_Functions.Semantic_Score import semantic_search
from App.Backend.Annotation_Functions.Hybrid_Score import hybrid_search
from App.Backend.Distillation_Functions.Numerical_Filtering import numerical_search

app = FastAPI(title="Deconstructed Pipeline API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

task_registry: Dict[str, Any] = {}

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


@app.get("/api/task/status/{task_id}")
def get_task_status(task_id: str):
    """Exposed endpoint to check up on background thread execution updates."""
    if task_id not in task_registry:
        raise HTTPException(status_code=404, detail="Task ID not registered.")
    return task_registry[task_id]


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




DATA_DIR = "./App/Backend/CSVs"
HTML_DIR = "./App/Backend/Visualizations"

@app.get("/api/catalog/csv")
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
            
            try:
                df_header = pandas.read_csv(path, nrows=0)
                columns = list(df_header.columns)
                
                with open(path, 'rb') as f:
                    row_count = sum(1 for _ in f) - 1 
                
                catalog_info.append(f"### {file}")
                catalog_info.append(f"- **Size:** {size_mb:.2f} MB ({row_count} rows)")
                catalog_info.append(f"- **Columns:** {', '.join(columns)}\n")
            except Exception as e:
                catalog_info.append(f"### {file}\n- **Error reading file:** {str(e)}\n")

    return "\n".join(catalog_info)

@app.get("/api/catalog/html")
def list_html_files() -> str:
    """Returns a list of all currently generated HTML app files."""
    catalog_info = ["# HTML Visualizations Catalog\n"]
    
    # 1. Explicitly check if the directory exists (mirrors your CSV setup)
    if not os.path.exists(HTML_DIR):
        return f"Error: HTML directory '{HTML_DIR}' not found."

    # 2. Use os.listdir instead of glob for consistent behavior
    files = [f for f in os.listdir(HTML_DIR) if f.endswith(".html")]
    
    if not files:
        return "No HTML apps generated yet."
        
    # 3. Add dynamic file data (like size) to ensure the payload changes
    #    This forces the MCP client to recognize it as fresh data.
    for file in files:
        path = os.path.join(HTML_DIR, file)
        try:
            size_kb = os.path.getsize(path) / 1024
            catalog_info.append(f"- **{file}** ({size_kb:.2f} KB)")
        except Exception as e:
            catalog_info.append(f"- **{file}** (Error reading file: {str(e)})")

    return "\n".join(catalog_info)

@app.get("/api/data/csv-segment")
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

    usecols = None # 
    if columns.lower() != "all":
        usecols = [col.strip() for col in columns.split(",")]

    try:
        df = pandas.read_csv(
            path,
            skiprows=range(1, start_row + 1),
            nrows=num_rows,
            usecols=usecols
        )
        
        if df.empty:
            return "No data found at this row segment (End of file reached)."

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


mcp = FastMCP.from_fastapi(app)

mcp_app = mcp.http_app()


combined_app = FastAPI(
    title="Deconstructed Pipeline API (With MCP Integration)",
    description="Atomic Data Science execution blocks serving Frontend and AI Agents.",
    lifespan=mcp_app.lifespan, 
    routes=[
        *mcp_app.routes,
        *app.routes,
    ]
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(combined_app, host="127.0.0.1", port=8000)