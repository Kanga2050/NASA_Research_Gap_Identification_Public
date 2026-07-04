"""Bridge between the dashboard chat column and Google's Gemini models.

Gemini is wired to the platform's own MCP server -- the same ``FastMCP`` object
``Server.py`` publishes at ``/mcp`` -- through an in-memory client, so the agent
can read the signed-in user's data and queue pipeline tasks with the exact same
tools an external MCP client would use.

The MCP tools authenticate the caller by an ``api_key`` argument. We never show
that key to the model: it is stripped from the function declarations Gemini sees
and injected server-side on every tool call, so the agent always acts as -- and
only as -- the logged-in user whose key we were handed.

Each user brings their own Gemini API key and picks a model (both stored in
``AgentSettings``); this module is handed those values per turn.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

# The MCP runtime imports its helpers as top-level ``Servers.*`` (matching how
# Server.py wires sys.path), so make ``App/`` importable before we pull it in.
_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

# Cap the tool-use loop so a misbehaving model can't spin forever on one turn.
MAX_TOOL_ITERATIONS = 8

SYSTEM_PROMPT = (
    "You are the research assistant embedded in the Research Gap Identification "
    "dashboard. You help the signed-in user run and inspect their NLP analysis "
    "pipeline -- embedding, dimensionality reduction, clustering, keyword and "
    "semantic scoring, filtering, and OpenAlex scraping -- and browse the CSV "
    "and HTML files they own.\n\n"
    "Use the provided tools to look up the user's actual data and queue tasks "
    "instead of guessing. Pipeline tasks run asynchronously and return a "
    "task_id; when you queue one, tell the user it was queued and that they can "
    "watch its progress in the dashboard. Keep answers concise."
)


class AgentError(RuntimeError):
    """The agent could not complete a turn (bad config or an upstream failure)."""


def genai_installed() -> bool:
    """True when the Google GenAI SDK is importable (packaged with the app)."""
    try:
        import google.genai  # noqa: F401
    except Exception:
        return False
    return True


def run_agent_turn(
    gemini_api_key: str,
    model: str,
    user_api_key: str,
    history: list[dict],
    user_message: str,
) -> str:
    """Run one user turn and return Gemini's final text reply.

    ``history`` is the prior conversation as a list of ``{"role", "content"}``
    text messages (roles are ``"user"``/``"assistant"``); the returned reply
    should be appended to it by the caller.
    """
    if not gemini_api_key:
        raise AgentError("Add your Gemini API key in Settings to use the assistant.")
    try:
        return asyncio.run(_run_turn(gemini_api_key, model, user_api_key, history, user_message))
    except AgentError:
        raise
    except Exception as exc:  # SDK/MCP/network failures -> a clean chat error
        raise AgentError(str(exc) or exc.__class__.__name__) from exc


async def _run_turn(gemini_api_key, model, user_api_key, history, user_message) -> str:
    from google import genai
    from google.genai import types

    from fastmcp import Client

    from Servers.mcp_runtime import mcp

    client = genai.Client(api_key=gemini_api_key)
    contents = _history_to_contents(history, types)
    contents.append(types.Content(role="user", parts=[types.Part(text=user_message)]))

    async with Client(mcp) as mcp_client:
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[_gemini_tool(await mcp_client.list_tools(), types)],
            # We drive the tool loop ourselves so the user's key is injected on
            # each call; disable the SDK's own auto-calling.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        response = None
        for _ in range(MAX_TOOL_ITERATIONS):
            response = client.models.generate_content(
                model=model, contents=contents, config=config
            )

            calls = _function_calls(response)
            if not calls:
                return _text_of(response)

            # Echo the model turn back, then answer every function call.
            contents.append(response.candidates[0].content)
            response_parts = [
                types.Part.from_function_response(
                    name=call.name,
                    response={"result": await _call_tool(mcp_client, call.name, dict(call.args or {}), user_api_key)},
                )
                for call in calls
            ]
            contents.append(types.Content(role="user", parts=response_parts))

        # Exhausted the tool budget without a final answer.
        return _text_of(response) or (
            "I wasn't able to finish that request within the tool limit. "
            "Please try rephrasing or breaking it into smaller steps."
        )


def _history_to_contents(history: list[dict], types) -> list:
    contents = []
    for message in history:
        # Gemini names the model turn "model", not "assistant".
        role = "model" if message.get("role") == "assistant" else "user"
        contents.append(types.Content(role=role, parts=[types.Part(text=message.get("content", ""))]))
    return contents


def _gemini_tool(mcp_tools, types):
    """Build a Gemini Tool from MCP tool definitions, dropping the ``api_key``
    argument so the model neither sees nor supplies it."""
    declarations = []
    for tool in mcp_tools:
        schema = _clean_schema(dict(tool.inputSchema or {"type": "object", "properties": {}}))
        properties = dict(schema.get("properties") or {})
        properties.pop("api_key", None)
        schema["properties"] = properties
        required = [name for name in schema.get("required", []) if name != "api_key"]
        if required:
            schema["required"] = required
        else:
            schema.pop("required", None)
        # A function with no remaining parameters must declare no schema at all.
        parameters = schema if properties else None
        declarations.append(
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description or "",
                parameters_json_schema=parameters,
            )
        )
    return types.Tool(function_declarations=declarations)


def _clean_schema(node):
    """Strip JSON-Schema keywords Gemini's schema validator rejects."""
    if not isinstance(node, dict):
        return node
    cleaned = {}
    for key, value in node.items():
        if key in ("additionalProperties", "$schema", "title"):
            continue
        if key == "properties" and isinstance(value, dict):
            cleaned[key] = {name: _clean_schema(sub) for name, sub in value.items()}
        elif key == "items":
            cleaned[key] = _clean_schema(value)
        else:
            cleaned[key] = value
    return cleaned


def _function_calls(response):
    calls = []
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return calls
    for part in (getattr(candidates[0].content, "parts", None) or []):
        call = getattr(part, "function_call", None)
        if call is not None:
            calls.append(call)
    return calls


async def _call_tool(mcp_client, name: str, tool_input: dict, user_api_key: str) -> str:
    args = dict(tool_input or {})
    args["api_key"] = user_api_key  # inject the caller's identity server-side
    try:
        result = await mcp_client.call_tool(name, args)
    except Exception as exc:
        return f"Tool {name} failed: {exc}"
    return _stringify_tool_result(result)


def _stringify_tool_result(result) -> str:
    """Render a FastMCP CallToolResult as text for a function_response."""
    data = getattr(result, "data", None)
    if data is not None:
        try:
            return json.dumps(data, default=str)
        except (TypeError, ValueError):
            return str(data)

    parts = [
        text
        for block in (getattr(result, "content", None) or [])
        if (text := getattr(block, "text", None))
    ]
    return "\n".join(parts) if parts else "(no output)"


def _text_of(response) -> str:
    return (getattr(response, "text", None) or "").strip()
