"""HTTP MCP server for backlog-agent.

Single long-running process that:
- Serializes writes with an asyncio lock (single-writer semantics)
- Auto-commits and pushes after each successful write
- Answers natural-language queries via an embedded Claude call (query tool)
- Serves all existing backlog tools over StreamableHTTP so multiple sessions
  can connect without spawning per-session processes

Configuration (inherits all BACKLOG_* vars from server.py):
    BACKLOG_AGENT_HOST    Bind address (default: 127.0.0.1)
    BACKLOG_AGENT_PORT    Bind port (default: 8765)
    ANTHROPIC_API_KEY     Required for the query tool; other tools work without it
    BACKLOG_AGENT_MODEL   Claude model for query (default: claude-sonnet-4-6)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

import uvicorn
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import TextContent, Tool
from starlette.applications import Starlette
from starlette.routing import Mount

from .agent import query_backlog
from .git_ops import commit_and_push
from .server import (
    BACKLOG_PATH,
    REPO_ROOT,
    SCORES_PATH,
    TOOLS as _STDIO_TOOLS,
    tool_add_item,
    tool_find_refs,
    tool_get_item,
    tool_get_score,
    tool_lint,
    tool_list_items,
    tool_list_sections,
    tool_set_score,
    tool_update_status,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Write-lock and success detection
# ---------------------------------------------------------------------------

_write_lock = asyncio.Lock()

_WRITE_HANDLERS: dict[str, Any] = {
    "add_item": tool_add_item,
    "update_status": tool_update_status,
    "set_score": tool_set_score,
}

_READ_HANDLERS: dict[str, Any] = {
    "list_items": tool_list_items,
    "get_item": tool_get_item,
    "get_score": tool_get_score,
    "find_refs": tool_find_refs,
    "list_sections": tool_list_sections,
    "lint": tool_lint,
}

_FAILURE_INDICATORS = ("rolled back", "not found", "failed", "required", "unknown status", "heading not found")


def _is_write_success(result: str) -> bool:
    rl = result.lower()
    return not any(x in rl for x in _FAILURE_INDICATORS)


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

server = Server("backlog-agent")

_QUERY_TOOL = (
    "query",
    (
        "Ask a natural-language question about the backlog. Returns a reasoned answer. "
        "Examples: 'What are the top items related to VPN?', "
        "'Which items are ready to pick up?', 'What epics do we have?', "
        "'Which items are blocked by #3?'. Requires ANTHROPIC_API_KEY."
    ),
    {
        "type": "object",
        "properties": {"question": {"type": "string", "description": "Natural-language question about the backlog"}},
        "required": ["question"],
    },
)

_ALL_TOOLS: list[tuple] = list(_STDIO_TOOLS) + [(*_QUERY_TOOL, None)]


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return [
        Tool(name=name, description=desc, inputSchema=schema)
        for name, desc, schema, _ in _ALL_TOOLS
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        result = await _dispatch(name, arguments or {})
    except Exception as e:
        result = f"{type(e).__name__}: {e}"
    return [TextContent(type="text", text=str(result))]


async def _dispatch(name: str, args: dict[str, Any]) -> str:
    if name == "query":
        backlog_text = BACKLOG_PATH.read_text()
        scores_text = SCORES_PATH.read_text() if SCORES_PATH.exists() else ""
        return query_backlog(args.get("question", ""), backlog_text, scores_text)

    if name in _READ_HANDLERS:
        return _READ_HANDLERS[name](args)

    if name in _WRITE_HANDLERS:
        async with _write_lock:
            result = _WRITE_HANDLERS[name](args)
            if _is_write_success(result) and os.environ.get("BACKLOG_AGENT_AUTOCOMMIT") == "1":
                try:
                    commit_and_push(REPO_ROOT, f"backlog: {name}")
                except Exception as e:
                    logger.warning("commit/push failed after %s: %s", name, e)
        return result

    return f"Unknown tool: {name}"


# ---------------------------------------------------------------------------
# Starlette / uvicorn wiring
# ---------------------------------------------------------------------------

session_manager = StreamableHTTPSessionManager(
    app=server,
    stateless=True,
)


@contextlib.asynccontextmanager
async def _lifespan(app: Starlette) -> AsyncIterator[None]:
    async with session_manager.run():
        yield


starlette_app = Starlette(
    routes=[Mount("/mcp/", app=session_manager.handle_request)],
    lifespan=_lifespan,
)


def run() -> None:
    """Console-script entrypoint: `backlog-agent`."""
    logging.basicConfig(level=logging.INFO)
    host = os.environ.get("BACKLOG_AGENT_HOST", "127.0.0.1")
    port = int(os.environ.get("BACKLOG_AGENT_PORT", "8765"))
    logger.info("backlog-agent starting on %s:%d", host, port)
    uvicorn.run(starlette_app, host=host, port=port)
