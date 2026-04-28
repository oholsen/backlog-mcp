# backlog-mcp

MCP server that exposes a markdown-table backlog — and an optional CSV scoring
sidecar — to MCP-aware agents (Claude Code, Gemini CLI, Codex, Kiro, etc.).
Lets an agent answer "what's ready and high-value?" via tool calls instead of
dragging the whole `Backlog.md` into context.

## Why

If your project tracks work as markdown table rows in a single `Backlog.md`,
two problems show up at scale:

- Reading the whole file into agent context is wasteful.
- Triage queries ("ready items, complexity ≤ 2, value ≥ 4") are brittle as
  ad-hoc grep.

`backlog-mcp` wraps that file with a small MCP server. The markdown stays the
source of truth — direct edits, git history, and `git grep` cross-references
all keep working. Agents call structured tools instead of regex-editing prose.

## Backlog format

Plain markdown table rows with this column shape:

```markdown
| # | File | Severity | Description |
|---|---|---|---|
| 627 | src/main.rs | High | **Sensor crash on missing capture interface.** Detect early; exit cleanly. |
| ~~16~~ | ~~src/device.rs~~ | ~~Minor~~ | **DONE (PR #227, 2026-04-27).** … |
```

Conventions the server understands:

- **Open**: `| <id> | <files> | <severity> | <description> |`
- **In progress**: description starts with `**IN PROGRESS (branch-name)**`
- **Done**: id/files/severity strikethroughed (`~~…~~`), description starts with `**DONE …**`
- **Archive**: rows under a `## Done — archive` heading (configurable prefix)

Sections are `## ` headings; subsections are `### `.

## Optional scoring sidecar

`Backlog-Scores.csv` next to `Backlog.md`:

```csv
id,complexity,value,ready,blocked_by,tags,notes
627,2,4,Y,,infra;customer-facing,sensor crash on missing iface
```

- `complexity`, `value`: 1–5
- `ready`: `Y` / `N` / `partial`
- `blocked_by`: comma-separated IDs
- `tags`: semicolon-separated free-form

Lines starting with `#` are comments. The server runs without the CSV — score
filters just match nothing if it's absent.

## Install

```sh
pip install git+https://github.com/oholsen/backlog-mcp
```

(Once published to PyPI: `pip install backlog-mcp`.)

This installs two console scripts:

- `backlog-mcp` — the MCP server
- `backlog-lint` — the hygiene CLI

## Configuration

All paths are environment-driven so the server can serve any project's backlog
without code changes:

| Env var | Default | Purpose |
|---|---|---|
| `BACKLOG_PATH` | `docs/Backlog.md` | Markdown backlog |
| `BACKLOG_SCORES` | `docs/Backlog-Scores.csv` | Scoring CSV (optional; tools no-op if missing) |
| `BACKLOG_REPO_ROOT` | `git rev-parse --show-toplevel` | Repo root for `git grep` / branch checks |
| `BACKLOG_ARCHIVE_PREFIX` | `Done` | Prefix matching the archive `## ` heading |

## Wire to Claude Code / Gemini CLI

Drop a `.mcp.json` at your project root:

```json
{
  "mcpServers": {
    "backlog": {
      "command": "backlog-mcp",
      "env": {
        "BACKLOG_PATH": "docs/Backlog.md",
        "BACKLOG_SCORES": "docs/Backlog-Scores.csv"
      }
    }
  }
}
```

Claude Code picks this up on session start; it'll prompt to approve the server
the first time.

## Tools

### Read (Phase 1)

| Tool | What it does |
|---|---|
| `list_items` | Filter open items by status / section / severity / score / tag |
| `get_item` | Full description + score + status for one item |
| `get_score` | Score row only (cheap pre-filter) |
| `find_refs` | `git grep` for `#<id>` across the whole repo |
| `list_sections` | Enumerate sections + open-item counts |
| `lint` | Run hygiene checks, return findings |

### Write (Phase 2 — gated on Phase 1 stability in your project)

| Tool | What it does |
|---|---|
| `add_item` | Create a new item; auto-assign next free ID; lint-verify, roll back on failure |
| `update_status` | Flip in_progress / done / open; requires `branch` for in_progress |
| `set_score` | Insert or update a row in the scoring CSV |

## CLI: `backlog-lint`

```sh
backlog-lint                          # uses BACKLOG_PATH or docs/Backlog.md
backlog-lint --backlog path/to/X.md
backlog-lint --skip-branch-check      # no network; skip stale-marker check
```

Three checks (each fails the run with exit 1):

1. **Duplicate IDs** across the whole file (open + archive).
2. **Unresolved git merge-conflict markers**.
3. **Stale `IN PROGRESS (branch-name)` markers** — branches not on origin
   (typically a merged-and-deleted PR; flip the marker to **DONE** or reset it).

CI usage (GitHub Actions):

```yaml
- uses: actions/checkout@v4
  with: { fetch-depth: 0 }
- run: pip install git+https://github.com/oholsen/backlog-mcp
- run: backlog-lint
```

## Limitations

- **Concurrent edits.** Two agents writing simultaneously will race. v1 has no
  file lock; rely on session-level coordination until this becomes a real
  problem.
- **Move-to-archive.** `update_status status=done` flips the row in place but
  doesn't relocate to the archive section. Periodic manual sweep covers it.
- **Cross-reference checking.** Currently deferred — prose mixes "(PRs #X, #Y)"
  groups, "Agents.md #6" anchors, and "the #1 finding" with real refs; needs a
  smarter parser than is currently warranted.

## License

MIT.
