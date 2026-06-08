# Backlog.md format specification

## Item formats

The parser reads **two** shapes (below), but `add_item` only ever **writes** the
heading format — most new items are long design notes or findings, so the heading
shape is the single creation format. Existing table rows remain valid to read and
edit in place.

### Table rows (legacy / manual)

```
| # | Status | File | Description |
|---|--------|------|-------------|
| 42 | [open] | src/foo.rs | Short description. |
```

Four columns, in order: `#` (integer ID), `Status` (bracket tag), `File` (file path or
comma-separated list), `Description` (free text).

### Rich heading items (items with extended body)

```
### #42 [open] Short title

Free-form markdown body — diagrams, checklists, links, etc.

```

The `### #NNN` line carries the ID and status tag. Body ends at the next `##` or `###`
boundary. No status tag in the body.

---

## Status tags

| Tag | Meaning |
|-----|---------|
| `[open]` | Not started |
| `[in-progress: branch-name]` | Active; worktree / branch name follows the colon |
| `[done: PR #N, YYYY-MM-DD]` | Merged — **delete the item** from Backlog.md |
| `[done-partial: PR #N]` | Partially shipped; leave the item open |

Rules:
- Status lives in the **header only** — never duplicated in the item body.
- When an item is marked `done`, delete it from `Backlog.md` and append an entry to
  `CHANGELOG-INBOX.md`. Done items are not archived inside the backlog file.

---

## ID assignment

IDs are monotonically increasing integers and are **never reused**. The source of
truth is a durable marker near the top of the file:

```markdown
<!-- next-id: 1199 -->
```

`add_item` reads this marker, assigns its value as the new ID, and bumps it by one —
all under a file lock, so concurrent callers never collide. The marker survives DONE
deletions, which a `max(live IDs) + 1` scan does **not**: because DONE items are
deleted (not archived), once the highest item is closed the live max drops and a scan
would re-issue its number.

If the marker is missing (e.g. a file that predates it), `add_item` falls back to
`max(live IDs) + 1` and writes the marker on the next add. Reseed it manually to
`max(all IDs ever assigned) + 1` — cross-checking any deleted-item record
(`CHANGELOG-INBOX`, `CHANGELOG`) so the seed sits above retired IDs.

---

## Section structure

```markdown
# Backlog

## Section Name

| # | Status | File | Description |
|---|--------|------|-------------|
| 1 | [open] | src/a.rs | Table-style item. |

### #2 [in-progress: feat-branch] Rich item title

Extended body with details.

## Inbox

| # | Status | File | Description |
|---|--------|------|-------------|
| 3 | [open] | src/b.rs | Newly filed item. |
```

- Sections are `##` headings.
- New items default to `## Inbox` unless a section is specified.
- The `## Done — archive` section is **not used** — done items are deleted, not moved.

---

## CHANGELOG-INBOX.md append format

When marking an item done, append a line like:

```
- #42 fixed the thing (PR #99, 2026-05-31)
```

below the `<!-- append new DONE lines below this line -->` comment.
