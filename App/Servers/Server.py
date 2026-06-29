from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from api_funcs import app as base_api
from mcp_funcs import mcp

mcp_app = mcp.http_app()

combined_app = FastAPI(
    title="Deconstructed Pipeline API (With MCP Integration)",
    description="Atomic Data Science execution blocks serving Frontend and AI Agents.",
    lifespan=mcp_app.lifespan, 
    routes=[
        *mcp_app.routes,
        *base_api.routes,
    ]
)

combined_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    uvicorn.run(combined_app, host="127.0.0.1", port=8000)