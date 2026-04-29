# Backlog

Open items.

## Section A

| # | File | Description |
|---|---|---|
| 1 | src/backlog_mcp/server.py | **Add list_sections subsection counts.** Break down open items per subsection, not just per top-level section. |
| 2 | src/backlog_mcp/server.py | **IN PROGRESS (feat-2)** **Serialise concurrent writes with asyncio lock.** Two stdio sessions racing on the same file corrupt the backlog. |

### Subsection X

| # | File | Description |
|---|---|---|
| 3 | src/backlog_mcp/lint.py | **Cross-reference validation.** Distinguish `(PR #2)` citations from natural-language `#` uses. |

## Section B

| # | File | Description |
|---|---|---|
| 10 | src/backlog_mcp/parser.py | **Handle multi-file cell values.** Parser splits on `,` but paths with commas in names break the split. |

## Done — archive

### Section A

| # | File | Description |
|---|---|---|
| ~~5~~ | ~~src/e.rs~~ | **DONE (PR #99).** Archived item. |
