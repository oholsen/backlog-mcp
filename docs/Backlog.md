# Backlog

## Network Server

HTTP MCP server so multiple sessions share one process and one writer.

| # | File | Description |
|---|---|---|
| ~~2~~ | ~~src/backlog_mcp/server_http.py~~ | **DONE** **HTTP MCP server with write lock and query tool.** Single long-running process; sessions connect via StreamableHTTP. Auto-commits and pushes after each write. Requires `anthropic` extra for the `query` tool. |
| 3 | src/backlog_mcp/server_http.py | **Auth for backlog-agent.** Shared-secret header (`BACKLOG_AGENT_TOKEN`) to restrict write access to trusted callers. |
| 4 | docs/ | **Docker / deployment guide.** Dockerfile and compose snippet for hosting backlog-agent as a team service. |

## Backlog Management

| # | File | Description |
|---|---|---|
| 6 | src/backlog_mcp/lint.py | **Cross-reference validation.** Smarter prose parser to distinguish `(PR #42)` and `Agents.md #6` from natural-language uses of `#`. |
| 9 | src/backlog_mcp/server.py | **Invalidate the derived view on out-of-band `Backlog.md` edits — per-request stat-and-reparse (or file-watch).** The server can serve a stale/parsed-wrong view after `Backlog.md` is edited outside the server: reformatted by hand (re-bucketing sections, changing the `**DONE**` convention, moving the `<!-- CHANGELOG-INBOX -->` marker) or mutated by a direct editor while the process holds a cached parse. Concrete failure (2026-05-27): `get_item(925)` reported `Status: archived (DONE)` while the actual row was a plain *open* table row — status had been inferred from section *position* and/or a stale cache, not row markup. (Positional-status heuristic since fixed; this covers the staleness class underneath it.) Fix: on each tool call, compare `Backlog.md` mtime/hash against the cached parse and re-read if changed (a file-backed store can be effectively stateless — re-read is cheap), or inotify-watch the file. Acceptance: reformat `Backlog.md` by hand, then `get_item`/`list_items` return state consistent with the file with no server restart. Keep "status strictly from row markup" as an invariant. |
| ~~7~~ | ~~src/backlog_mcp/file_lock.py, src/backlog_mcp/server.py, src/backlog_mcp/server_http.py, src/backlog_mcp/git_ops.py~~ | **DONE** **Cross-process write atomicity for backlog write tools.** Original scope (fcntl lock for concurrent stdio sessions) widened after observing a race in the HTTP server: when two sessions wrote Backlog.md within the same window, `git add -A` in `commit_and_push` swept both changes into the first commit, leaving the second commit empty (and its message orphaned from its contents). Fix: (a) new `file_lock.backlog_lock(BACKLOG_PATH)` — fcntl `LOCK_EX` on a sibling `.lock` file — wraps the entire read-modify-write-commit-push pipeline in both server.py (stdio) and server_http.py (HTTP); (b) `commit_and_push` now takes a `paths=[...]` argument and stages only those, avoiding sweeping concurrent writes from outside the lock; (c) empty-commit guard skips `git commit` when staging yields no diff (rather than raising). Cross-process test in `tests/test_file_lock.py`; staging + empty-commit tests in `tests/test_git_ops.py`. |

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
| ~~5~~ | ~~src/backlog_mcp/server.py~~ | **DONE** **Move-to-archive on status=done.** `update_status status=done` now relocates the row to the end of the `## Done — archive` section's primary table (above any subsection beneath it), in addition to the in-place strikethrough + `**DONE**` marker. Skipped when the item is already in the archive section, when it's a heading-format item, or when the archive heading isn't present (falls back to in-place rewrite). Same `lint` + rollback envelope. |
