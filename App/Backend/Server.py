import sys
import os
import uuid
from typing import Dict, Any, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastmcp import FastMCP

# Add local paths
sys.path.append(os.path.join(os.getcwd(), 'Annotation_Functions'))
sys.path.append(os.path.join(os.getcwd(), 'Visualization_Functions'))

# Import your atomic functions
from Annotation_Functions.Embedder import add_embeddings_in_place
from Annotation_Functions.Dimensionality_Reducer import reduce_embeddings_with_umap
from Annotation_Functions.Clustering import cluster_with_hdbscan
from Visualization_Functions.Distance_Map import generate_intertopic_distance_map
from Annotation_Functions.Keyword_Score import keyword_search
from Annotation_Functions.Semantic_Score import semantic_search
from Annotation_Functions.Hybrid_Score import hybrid_search
from Distillation_Functions.Numerical_Filtering import numerical_search

# 1. Initialize FastAPI Application
app = FastAPI(title="Deconstructed Pipeline API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared memory log to trace atomic tasks asynchronously 
# Structure: { task_id: {"function": "...", "status": "processing/completed/failed", "result": "..."} }
task_registry: Dict[str, Any] = {}

# 2. Asynchronous Execution Helper
def run_async_step(task_id: str, function_name: str, func, *args, **kwargs):
    """Executes any pipeline step on a background thread and caches execution state."""
    try:
        task_registry[task_id] = {"function": function_name, "status": "processing"}
        print(f"[Engine] Running task {task_id} ({function_name})...")
        
        # Execute the actual imported function dynamically
        func(*args, **kwargs)
        
        task_registry[task_id]["status"] = "completed"
        task_registry[task_id]["result"] = f"Function '{function_name}' executed successfully."
    except Exception as e:
        task_registry[task_id]["status"] = "failed"
        task_registry[task_id]["error"] = str(e)

# --- 3. DUAL WORKFLOW EXPOSURES (HUMAN REST ENDPOINTS & AI MCP TOOLS) ---

# Schema for tracking task state
@app.get("/api/task/status/{task_id}")
def get_task_status(task_id: str):
    """Exposed to UI and Agents to check up on execution status."""
    if task_id not in task_registry:
        raise HTTPException(status_code=404, detail="Task ID not registered.")
    return task_registry[task_id]

# ----------------- STEP A: EMBEDDING GENERATION -----------------
class EmbedRequest(BaseModel):
    file_path: str
    text_column: str = "abstract"
    embedding_column: str = "abstract_embedding"
    model: str = "allenai/specter2_base"

@app.post("/api/pipeline/embed")
def trigger_embed(data: EmbedRequest, bg_tasks: BackgroundTasks) -> Dict[str, str]:
    """Generates embeddings inside the specified column path."""
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
    """Applies dimensional reduction to a target coordinate space (e.g. 2d or 5d)."""
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
    """Processes dynamic spatial grouping metrics using HDBSCAN."""
    task_id = str(uuid.uuid4())
    bg_tasks.add_task(
        run_async_step, task_id, "cluster_with_hdbscan",
        cluster_with_hdbscan, data.file_path, data.coordinate_column, data.output_column, data.min_cluster_size, data.min_samples
    )
    return {"task_id": task_id, "status": "queued"}

# [You can similarly add endpoints for keyword_search, semantic_search, hybrid_search, and numerical_search here following the same blueprint]

# 4. Bind FastMCP automatically directly out of your FastAPI endpoints
mcp = FastMCP.from_fastapi(app)

# Convert the MCP configuration into an HTTP-compatible app layer
mcp_app = mcp.http_app()

# Merge both route schemas into a unified app so /docs remains active
combined_app = FastAPI(
    title="Deconstructed Pipeline API (With MCP Integration)",
    routes=[
        *mcp_app.routes,  # Houses the underlying MCP protocols
        *app.routes,      # Houses your REST API endpoints & /docs
    ]
)

if __name__ == "__main__":
    import uvicorn
    # Use standard uvicorn to run the merged app instead of mcp.run()
    uvicorn.run(combined_app, host="127.0.0.1", port=8000)