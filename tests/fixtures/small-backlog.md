# Backlog

Open items.

## Section A

| # | File | Severity | Description |
|---|---|---|---|
| 1 | src/backlog_mcp/server.py | Low | **Add list_sections subsection counts.** Break down open items per subsection, not just per top-level section. |
| 2 | src/backlog_mcp/server.py | High | **IN PROGRESS (feat-2)** **Serialise concurrent writes with asyncio lock.** Two stdio sessions racing on the same file corrupt the backlog. |

### Subsection X

| # | File | Severity | Description |
|---|---|---|---|
| 3 | src/backlog_mcp/lint.py | Medium | **Cross-reference validation.** Distinguish `(PR #2)` citations from natural-language `#` uses. |

## Section B

| # | File | Severity | Description |
|---|---|---|---|
| 10 | src/backlog_mcp/parser.py | Low | **Handle multi-file cell values.** Parser splits on `,` but paths with commas in names break the split. |

## Done — archive

### Section A

| # | File | Severity | Description |
|---|---|---|---|
| ~~5~~ | ~~src/e.rs~~ | ~~Low~~ | **DONE (PR #99).** Archived item. |
