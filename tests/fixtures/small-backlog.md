# Backlog

Open items.

## Section A

| # | Status | File | Description |
|---|--------|------|-------------|
| 1 | [open] | src/backlog_mcp/server.py | **Add list_sections subsection counts.** Break down open items per subsection, not just per top-level section. |
| 2 | [in-progress: feat-2] | src/backlog_mcp/server.py | **Serialise concurrent writes with asyncio lock.** Two stdio sessions racing on the same file corrupt the backlog. |

### Subsection X

| # | Status | File | Description |
|---|--------|------|-------------|
| 3 | [open] | src/backlog_mcp/lint.py | **Cross-reference validation.** Distinguish `(PR #2)` citations from natural-language `#` uses. |

## Section B

| # | Status | File | Description |
|---|--------|------|-------------|
| 10 | [open] | src/backlog_mcp/parser.py | **Handle multi-file cell values.** Parser splits on `,` but paths with commas in names break the split. |
