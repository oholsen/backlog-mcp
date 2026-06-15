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
| # | File | Description |
|---|---|---|
| 12 | src/auth/session.py | **Session token not rotated after privilege escalation.** Rotate on role change. |
| ~~3~~ | ~~src/api/routes.py~~ | **DONE (PR #41, 2026-03-15).** Rate-limit login endpoint. |
```

Conventions the server understands:

- **Open**: `| <id> | <files> | <description> |`
- **In progress**: description starts with `**IN PROGRESS (branch-name)**`
- **Done**: id/files strikethroughed (`~~…~~`), description starts with `**DONE …**`
- **Archive**: rows under a `## Done — archive` heading (configurable prefix)

Sections are `## ` headings; subsections are `### `.

## Optional scoring sidecar

`Backlog-Scores.csv` next to `Backlog.md`:

```csv
id,complexity,value,ready,blocked_by,tags,notes
# complexity and value: 1 (low) – 5 (high); net priority ≈ value / complexity
12,2,4,Y,,auth;security,session not rotated after privilege escalation
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

This installs three console scripts:

- `backlog-mcp` — the stdio MCP server (one process per session)
- `backlog-agent` — the HTTP MCP server (shared, single-writer; see below)
- `backlog-lint` — the hygiene CLI

For the `query` tool install the `agent` extra:

```sh
pip install 'git+https://github.com/oholsen/backlog-mcp[agent]'
```

## Configuration

All paths are environment-driven so the server can serve any project's backlog
without code changes:

| Env var | Default | Purpose |
|---|---|---|
| `BACKLOG_PATH` | `Backlog.md` | Markdown backlog |
| `BACKLOG_SCORES` | `Backlog-Scores.csv` next to `BACKLOG_PATH` | Scoring CSV (optional; tools no-op if missing) |
| `BACKLOG_REPO_ROOT` | `git rev-parse --show-toplevel` | Repo root for `git grep` / branch checks |
| `BACKLOG_ARCHIVE_PREFIX` | `Done` | Prefix matching the archive `## ` heading |

## Multi-agent workflow

```
                       git repository
                       ──────────────
         ┌─────────────────────────────────────────────────┐
         │                                                 │
         │  worktree: main        worktree: feat/auth      │
         │  ┌──────────────┐      ┌──────────────────┐     │
         │  │ Backlog.md   │      │ src/auth/…       │     │
         │  │ Backlog-     │      │ tests/auth/…     │     │
         │  │  Scores.csv  │      └──────────────────┘     │
         │  └──────┬───────┘                               │
         │         │              worktree: feat/api        │
         │         │              ┌──────────────────┐     │
         │         │              │ src/api/…        │     │
         │         │              │ tests/api/…      │     │
         └─────────┼──────────────┴──────────────────┴─────┘
                   │ reads / writes
                   ▼
         ┌─────────────────────┐
         │    backlog-agent    │   HTTP :8765
         │    (single writer,  │   ◄──────────────────────┐
         │     auto-commit)    │                          │
         └─────────────────────┘                   MCP tool calls

              Agent A                 Agent B                 Agent C
          ┌───────────────┐      ┌───────────────┐      ┌───────────────┐
          │ session: main │      │ feat/auth     │      │ feat/api      │
          │               │      │               │      │               │
          │ context:      │      │ context:      │      │ context:      │
          │ • full repo   │      │ • auth files  │      │ • api files   │
          │ • backlog     │      │ • backlog     │      │ • backlog     │
          │ • scores CSV  │      │ • scores CSV  │      │ • scores CSV  │
          │               │      │               │      │               │
          │ asks:         │      │ asks:         │      │ asks:         │
          │ • top priority│      │ • next item   │      │ • sequencing  │
          │ • value /     │      │   touching    │      │   — which     │
          │   complexity  │      │   auth files  │      │   items share │
          │   ranking     │      │ • blocked_by  │      │   api files?  │
          │ • what's      │      │   resolution  │      │ • file-level  │
          │   ready now?  │      │   order       │      │   conflict    │
          └───────┬───────┘      └───────┬───────┘      └───────┬───────┘
                  └──────────────────────┴──────────────────────┘
                                         │
                                    HTTP :8765
```

## backlog-agent — shared HTTP server

For teams or when multiple agent sessions share the same backlog repo,
`backlog-agent` runs as a single long-running process:

- **Single writer** — an `asyncio` lock serialises all writes; no file races.
- **Auto-commit** — each successful write is committed and pushed.
- **`query` tool** — natural-language questions answered by an embedded Claude
  call with the full backlog in context (e.g. "what are the top auth items?").

```sh
BACKLOG_PATH=Backlog.md \
BACKLOG_REPO_ROOT=. \
ANTHROPIC_API_KEY=sk-... \
backlog-agent          # listens on 127.0.0.1:8765 by default
```

| Env var | Default | Purpose |
|---|---|---|
| `BACKLOG_AGENT_HOST` | `127.0.0.1` | Bind address |
| `BACKLOG_AGENT_PORT` | `8765` | Bind port |
| `BACKLOG_AGENT_AUTOCOMMIT` | unset | Set to `1` to git-commit (and push) after each successful write. Staging is **hunk-safe**: only this write's `before`→`after` hunks are committed, applied on top of `HEAD` via a 3-way merge, so concurrent unstaged edits another session left in `Backlog.md` are never swept in. If a concurrent edit conflicts with this write, or the index already has staged changes, the write is left uncommitted (and logged) rather than force-committed. |
| `BACKLOG_AGENT_PUSH` | `1` | When autocommit is on, set to `0` to commit locally without `git push`. |
| `ANTHROPIC_API_KEY` | — | Required for the `query` tool only |
| `BACKLOG_AGENT_MODEL` | `claude-sonnet-4-6` | Claude model for `query` |

Wire each session to it instead of spawning per-session stdio processes. Two
files per worktree:

**`.mcp.json`** at the worktree root — declares the server:

```json
{
  "mcpServers": {
    "backlog": {
      "type": "http",
      "url": "http://localhost:8765/mcp/"
    }
  }
}
```

**`.claude/settings.json`** — opts the project in to the HTTP server (Claude
Code requires explicit activation for HTTP MCP servers):

```json
{
  "enabledMcpjsonServers": ["backlog"]
}
```

Without `enabledMcpjsonServers` the `.mcp.json` entry is ignored even when the
agent is running.

## Wire to Claude Code / Gemini CLI (stdio)

Drop a `.mcp.json` at your project root:

```json
{
  "mcpServers": {
    "backlog": {
      "command": "backlog-mcp",
      "env": {
        "BACKLOG_PATH": "Backlog.md"
      }
    }
  }
}
```

Claude Code picks this up on session start; it'll prompt to approve the server
the first time.

### Sample CLAUDE.md

Tell Claude Code how to use the backlog by adding a `CLAUDE.md` at your repo root. A real-world example from a multi-worktree Rust project:

```markdown
## Documentation Policy

Backlog.md lives at the repo root. It is managed exclusively on `main` — never
on worktrees or feature branches. Full rules (ID assignment, CHANGELOG flow,
docs/ audience buckets, customer-facing doc lifecycle):
**[`docs/process/Docs-Policy.md`](docs/process/Docs-Policy.md)**.

**Backlog keeper agent:** Use the `backlog-keeper` subagent
(`.claude/agents/backlog-keeper.md`) for all mechanical Backlog.md edits —
new items, IN PROGRESS flips, DONE flips, and CHANGELOG-INBOX entries. Invoke
it via the Agent tool with a plain-English instruction (e.g. "mark #677 DONE,
PR #264, 2026-04-29"). The agent handles ID assignment, collision checks, and
CHANGELOG-INBOX appends. It only operates on `main` — never on
feature branches.

## Worktree Pre-Flight (before `EnterWorktree`)

Always run the pre-flight checklist before creating a worktree.

Short version:
1. Check for conflicts: `grep "IN PROGRESS" Backlog.md`.
2. Mark your items `**IN PROGRESS (branch-name)**` on `main` (unstaged) — or
   invoke the `backlog-keeper` agent: "mark #NNN in progress on branch-name".
3. Create the worktree at `~/src/worktrees/<branch-name>` (not inside the
   workspace).

## Worktree Lifecycle

After merge:
1. `gh pr merge <N> --squash`
2. `git worktree remove ~/src/worktrees/<branch>`
3. `git branch -d <branch-name> && git pull`
4. Flip IN PROGRESS → DONE via the backlog-keeper agent.
```

The key patterns this illustrates:

- **Dedicated subagent** for backlog edits keeps mechanical writes off the main session context.
- **main-only rule** — `Backlog.md` lives on `main`; worktree sessions query via MCP but never edit the file directly.
- **Pre-flight + lifecycle hooks** baked into CLAUDE.md so the agent enforces the workflow without user prompting.

## Tools

### Read (Phase 1)

| Tool | What it does |
|---|---|
| `list_items` | Filter open items by status / section / score / tag / **files** (substring match against the files column) |
| `get_item` | Full description + score + status for one item |
| `get_score` | Score row only (cheap pre-filter) |
| `find_refs` | `git grep` for `#<id>` across the whole repo |
| `list_sections` | Enumerate sections + open-item counts |
| `lint` | Run hygiene checks, return findings |

### Write

| Tool | What it does |
|---|---|
| `add_item` | Create a new item; auto-assign next free ID; defaults to the `## Inbox` section. Pass `section` to target a specific topical section. Verifies via lint and rolls back on failure. |
| `update_status` | Flip in_progress / done / open; requires `branch` for in_progress |
| `set_score` | Insert or update a row in the scoring CSV |

### Reasoning (`backlog-agent` only)

| Tool | What it does |
|---|---|
| `query` | Natural-language question answered by Claude with the full backlog in context. Requires `ANTHROPIC_API_KEY`. |

`add_item` expects a `## Inbox` section in the backlog (above `## Done — archive`)
when no explicit section is given. Mirrors the `CHANGELOG-INBOX → CHANGELOG`
buffer pattern: file fast, curate periodically. If you don't want this flow,
pass an explicit `section` argument on every call.

## CLI: `backlog-lint`

```sh
backlog-lint                          # uses BACKLOG_PATH or Backlog.md
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

- **Concurrent edits (stdio).** Two `backlog-mcp` stdio processes writing
  simultaneously will race. Use `backlog-agent` (HTTP) for shared access.
- **Cross-reference checking.** Currently deferred — prose mixes "(PRs #X, #Y)"
  groups, "Agents.md #6" anchors, and "the #1 finding" with real refs; needs a
  smarter parser than is currently warranted.

## License

MIT.
