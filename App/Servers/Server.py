import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
app_dir = os.path.abspath(os.path.join(current_dir, ".."))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
for path in (project_root, app_dir):
    if path not in sys.path:
        sys.path.insert(0, path)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "App.Frontend.webapp.settings")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from Servers.api_runtime import app as base_api
from Servers.mcp_runtime import mcp
from App.Frontend.webapp.asgi import application as django_app

mcp_app = mcp.http_app(path="/mcp")

combined_app = FastAPI(
    title="Deconstructed Pipeline API (With MCP Integration)",
    description="Atomic Data Science execution blocks serving Frontend and AI Agents.",
    lifespan=mcp_app.lifespan, 
    routes=[
        *mcp_app.routes,
        *base_api.routes,
    ]
)

_cors_origins = [o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()]

combined_app.add_middleware(
    CORSMiddleware,
    # allow_origins=["*"] combined with allow_credentials=True is not a legal CORS
    # response (browsers reject it) so it silently degrades to reflecting whatever
    # Origin the caller sends -- i.e. any site can make credentialed requests against
    # the Django session cookie mounted below. Require an explicit allowlist instead.
    allow_origins=_cors_origins,
    allow_credentials=bool(_cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

combined_app.mount("/", django_app)

if __name__ == "__main__":
    host = os.environ.get("SERVER_HOST", "127.0.0.1")
    port = int(os.environ.get("SERVER_PORT", "8000"))
    uvicorn.run(combined_app, host=host, port=port)