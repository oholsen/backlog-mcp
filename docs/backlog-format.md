# Backlog.md format specification

## Two item formats

### Table rows (simple items)

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

IDs are monotonically increasing integers. To find the highest existing ID:

```bash
grep -oP '(?<=^\| )\d+(?= \| )' Backlog.md | sort -n | tail -1
# or for heading-format items:
grep -oP '(?<=^### #)\d+' Backlog.md | sort -n | tail -1
```

The next free ID is `max + 1`. IDs are never reused.

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
