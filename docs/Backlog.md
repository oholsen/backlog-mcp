# Backlog

## Network Server

HTTP MCP server so multiple sessions share one process and one writer.

| # | File | Description |
|---|---|---|
| 2 | src/backlog_mcp/server_http.py | **IN PROGRESS (main)** **HTTP MCP server with write lock and query tool.** Single long-running process; sessions connect via StreamableHTTP. Auto-commits and pushes after each write. Requires `anthropic` extra for the `query` tool. |
| 3 | src/backlog_mcp/server_http.py | **Auth for backlog-agent.** Shared-secret header (`BACKLOG_AGENT_TOKEN`) to restrict write access to trusted callers. |
| 4 | docs/ | **Docker / deployment guide.** Dockerfile and compose snippet for hosting backlog-agent as a team service. |

## Backlog Management

| # | File | Description |
|---|---|---|
| 5 | src/backlog_mcp/server.py | **Move-to-archive on status=done.** `update_status` currently flips the row in place; optionally relocate it under `## Done — archive` in the same pass. |
| 6 | src/backlog_mcp/lint.py | **Cross-reference validation.** Smarter prose parser to distinguish `(PR #42)` and `Agents.md #6` from natural-language uses of `#`. |
| 7 | src/backlog_mcp/server.py | **File lock for concurrent stdio sessions.** `fcntl`-based advisory lock so two `backlog-mcp` stdio processes don't race on the same file. |

## Release

| # | File | Description |
|---|---|---|
| 8 | pyproject.toml | **Publish to PyPI.** Configure trusted-publisher workflow; tag v1.0.0 once HTTP server ships. |

## Inbox

Append-only buffer — file here, curate into sections periodically.

| # | File | Description |
|---|---|---|

## Done — archive

| # | File | Description |
|---|---|---|
| ~~1~~ | ~~src/backlog_mcp/server.py~~ | **DONE (v0.1.0).** Initial MCP server release — list, get, add, update-status, set-score, lint, find-refs. |
