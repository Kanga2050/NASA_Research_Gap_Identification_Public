"""Builds the REST and MCP pipeline surfaces from the function registry.

Both runtimes used to hand-write one wrapper per pipeline function -- ~35 Pydantic
models plus ~35 endpoints in `api_runtime`, and ~35 tools in `mcp_runtime`, each
restating the same argument list and re-describing the same function in slightly
different prose. Roughly 1,300 lines that did nothing but forward their arguments to
`queue_user_task`, and that silently rotted whenever a backend signature moved.

Now both are generated from `App.Backend.registry`, which already knows every
function's arguments, defaults, storage roots and documentation. Adding a pipeline
function to the platform means adding one registry entry -- the REST endpoint and the
MCP tool appear on their own, correct by construction.

The generated callables carry an explicit ``__signature__``. FastAPI and FastMCP both
introspect with ``inspect.signature()``, so a synthesized signature gives them exactly
what a hand-written ``def`` would: a full request model and OpenAPI schema on the REST
side, a full input schema on the MCP side.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable

from pydantic import Field, create_model

from App.Backend import registry
from App.Backend.registry import Function, Param
from App.Frontend.webapp.storage import user_csv_root, user_pdf_root, user_template_root

# A chart's .html lives right alongside the Studio recipe that made it (the
# "template" root); a paper's built report lives right alongside its own .json
# document (the "paper" root) -- there is no longer a standalone "html" root.
# Shared here (rather than duplicated in api_runtime.py and mcp_runtime.py) so the
# two runtimes can't drift on which storage root each kind resolves to.
ROOT_BUILDERS = {"csv": user_csv_root, "html": user_template_root, "pdf": user_pdf_root}

# The REST tag / MCP grouping each family of function is published under.
API_TAGS = {
    "import": "Import",
    "annotation": "Annotation",
    "distillation": "Distillation",
    "visualization": "Visualization",
}


def _annotation(param: Param) -> Any:
    return param.type


def _pydantic_field(param: Param):
    """One field of a generated request model: (type, FieldInfo)."""
    if param.required:
        return (param.type, Field(..., description=param.doc))
    return (param.type, Field(default=param.api_default(), description=param.doc))


def request_model(fn: Function):
    """The Pydantic request body for a function's REST endpoint, named as the
    hand-written models were (e.g. bar_chart -> BarChartRequest) so the OpenAPI schema
    keeps the same component names."""
    name = "".join(part.title() for part in fn.name.split("_")) + "Request"
    fields = {param.api_name: _pydantic_field(param) for param in fn.params}
    return create_model(name, **fields)


def _signature(params: list[inspect.Parameter]) -> inspect.Signature:
    # Required params must precede defaulted ones in a signature, regardless of the
    # order they are declared in (which follows the BACKEND's positional order).
    required = [p for p in params if p.default is inspect.Parameter.empty]
    optional = [p for p in params if p.default is not inspect.Parameter.empty]
    return inspect.Signature(required + optional)


def api_endpoint(fn: Function, model, queue: Callable, current_user) -> Callable:
    """The REST handler for one pipeline function: validate the body, queue the task,
    return {task_id, status}."""

    def endpoint(data, user):
        return queue(user, fn, {param.api_name: getattr(data, param.api_name) for param in fn.params})

    endpoint.__name__ = fn.name
    endpoint.__doc__ = fn.description
    endpoint.__signature__ = inspect.Signature([
        inspect.Parameter("data", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=model),
        inspect.Parameter("user", inspect.Parameter.POSITIONAL_OR_KEYWORD,
                          default=current_user, annotation=Any),
    ])
    return endpoint


def mcp_tool(fn: Function, queue: Callable, get_user: Callable) -> Callable:
    """The MCP tool for one pipeline function. Takes the caller's `api_key` as its
    first argument (that is how every tool on this server authenticates) followed by
    the function's own arguments, under their published MCP names."""

    def tool(**kwargs):
        user = get_user(kwargs.pop("api_key"))
        # Back onto the shared API vocabulary, for the one param MCP names differently.
        renamed = {p.mcp_name: p.api_name for p in fn.params if p.mcp_name != p.api_name}
        return queue(user, fn, {renamed.get(k, k): v for k, v in kwargs.items()})

    params = [inspect.Parameter("api_key", inspect.Parameter.KEYWORD_ONLY, annotation=str)]
    for param in fn.params:
        default = inspect.Parameter.empty if param.required else param.api_default()
        params.append(inspect.Parameter(
            param.mcp_name, inspect.Parameter.KEYWORD_ONLY,
            default=default, annotation=_annotation(param),
        ))

    tool.__name__ = fn.name
    tool.__doc__ = fn.description
    tool.__signature__ = _signature(params)
    tool.__annotations__ = {p.name: p.annotation for p in params}
    return tool


def queue_from_api(queue_user_task, root_builders):
    """Build the `queue(user, fn, api_kwargs)` both surfaces call.

    Maps the caller's API-named arguments back onto the backend's positional order and
    attaches the storage roots -- and any per-user third-party keys -- the function
    needs: the same translation the Django view does for form data, driven by the same
    registry entry.
    """

    def queue(user, fn: Function, api_kwargs: dict):
        # Imported lazily so this module stays importable without Django set up.
        from App.Frontend.portal.user_secrets import secret_kwargs

        args = [api_kwargs.get(param.api_name, param.api_default()) for param in fn.params]
        roots = {f"{root}_root": str(root_builders[root](user)) for root in fn.roots}
        return queue_user_task(user, fn.name, *args, **roots, **secret_kwargs(user, fn))

    return queue


def register_api_routes(app, queue, current_user) -> None:
    """Mount one POST endpoint per pipeline function onto a FastAPI app."""
    for fn in registry.ALL_FUNCTIONS:
        model = request_model(fn)
        app.post(
            f"/api/pipeline/{fn.route}",
            tags=[API_TAGS[fn.category]],
            summary=fn.summary,
            description=fn.description,
        )(api_endpoint(fn, model, queue, current_user))


def register_mcp_tools(mcp, queue, get_user) -> None:
    """Register one MCP tool per pipeline function."""
    for fn in registry.ALL_FUNCTIONS:
        mcp.tool(name=fn.name)(mcp_tool(fn, queue, get_user))
