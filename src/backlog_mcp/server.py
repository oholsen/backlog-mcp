"""MCP server exposing a markdown-table backlog to agents.

Reads/writes a `Backlog.md` table (and an optional `Backlog-Scores.csv` sidecar)
so MCP-aware agents can list / get / score / add / mark-status without dragging
the whole file into context.

Configuration is environment-driven so the server can serve any project's
backlog without code changes:

    BACKLOG_PATH            Path to the markdown backlog (default: Backlog.md)
    BACKLOG_SCORES          Path to the scoring CSV; optional, scoring tools no-op
                            if unset or missing (default: Backlog-Scores.csv next to BACKLOG_PATH)
    BACKLOG_REPO_ROOT       Repo root for git operations (default: parent of backlog;
                            falls back to `git rev-parse --show-toplevel`)
    BACKLOG_CHANGELOG_INBOX Path to the CHANGELOG-INBOX append buffer
                            (default: CHANGELOG-INBOX.md at repo root)
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .file_lock import backlog_lock
from .lint import lint_file
from .parser import (
    Item,
    Score,
    index_by_id,
    one_line_summary,
    parse_backlog,
    parse_backlog_text,
    parse_scores,
)


# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

def _resolve_repo_root(backlog_path: Path) -> Path:
    env = os.environ.get("BACKLOG_REPO_ROOT")
    if env:
        return Path(env).resolve()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=backlog_path.parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return backlog_path.parent.parent


BACKLOG_PATH = Path(os.environ.get("BACKLOG_PATH", "Backlog.md")).resolve()
SCORES_PATH = Path(os.environ.get("BACKLOG_SCORES", BACKLOG_PATH.parent / "Backlog-Scores.csv")).resolve()
REPO_ROOT = _resolve_repo_root(BACKLOG_PATH)
CHANGELOG_INBOX_PATH = Path(
    os.environ.get("BACKLOG_CHANGELOG_INBOX", str(REPO_ROOT / "CHANGELOG-INBOX.md"))
).resolve()


def _items() -> tuple[list[Item], dict[int, Item]]:
    items = parse_backlog(BACKLOG_PATH)
    return items, index_by_id(items)


def _scores() -> dict[int, Score]:
    if not SCORES_PATH.exists():
        return {}
    return parse_scores(SCORES_PATH)


# ----------------------------------------------------------------------------
# Tool implementations
# ----------------------------------------------------------------------------

def tool_list_items(args: dict[str, Any]) -> str:
    items, _ = _items()
    scores = _scores()

    status = (args.get("status") or "open").lower()
    section_filter = args.get("section")
    ready_filter = args.get("ready")
    max_c = args.get("max_complexity")
    min_v = args.get("min_value")
    tag_filter = args.get("tag")
    files_filter = args.get("files")
    limit = int(args.get("limit") or 50)

    out: list[str] = []
    for it in items:
        if status == "open" and (it.archived or it.in_progress):
            continue
        if status == "in_progress" and not it.in_progress:
            continue
        if status == "done" and not it.archived:
            continue
        if section_filter and section_filter.lower() not in (
            it.section + " " + (it.subsection or "")
        ).lower():
            continue
        if files_filter and files_filter.lower() not in it.files.lower():
            continue
        sc = scores.get(it.id)
        if ready_filter:
            if not sc or sc.ready.lower() != ready_filter.lower():
                continue
        if max_c is not None:
            if not sc or sc.complexity is None or sc.complexity > int(max_c):
                continue
        if min_v is not None:
            if not sc or sc.value is None or sc.value < int(min_v):
                continue
        if tag_filter:
            if not sc or tag_filter.lower() not in [t.lower() for t in sc.tags]:
                continue

        score_str = ""
        if sc and sc.complexity is not None and sc.value is not None:
            score_str = f" [C{sc.complexity}/V{sc.value}]"
        out.append(f"#{it.id}{score_str} {one_line_summary(it.description)}")
        if len(out) >= limit:
            break

    if not out:
        return "No items matched."
    suffix = f"\n\n({len(out)} match(es) — raise limit if needed)" if len(out) >= limit else ""
    return "\n".join(out) + suffix


def tool_get_item(args: dict[str, Any]) -> str:
    id_ = int(args["id"])
    _, by_id = _items()
    if id_ not in by_id:
        return f"#{id_} not found in {BACKLOG_PATH.name}"
    it = by_id[id_]
    sc = _scores().get(id_)
    section_path = it.section + (f" → {it.subsection}" if it.subsection else "")
    lines = [
        f"#{it.id}",
        f"Section: {section_path}",
        f"Status: {'archived (DONE)' if it.archived else ('in progress' if it.in_progress else 'open')}",
        f"Files: {it.files}",
    ]
    if sc:
        lines.append(
            f"Score: complexity={sc.complexity} value={sc.value} ready={sc.ready or '?'} "
            f"blocked_by={sc.blocked_by or '—'} tags={'; '.join(sc.tags) or '—'}"
        )
        if sc.notes:
            lines.append(f"Notes: {sc.notes}")
    else:
        lines.append("Score: (not yet scored)")
    lines.append("")
    lines.append("Description:")
    lines.append(it.description)
    if it.body:
        lines.append("")
        lines.append("Body:")
        lines.append(it.body)
    return "\n".join(lines)


def tool_get_score(args: dict[str, Any]) -> str:
    id_ = int(args["id"])
    sc = _scores().get(id_)
    if not sc:
        return f"#{id_} has no score"
    return json.dumps({
        "id": sc.id,
        "complexity": sc.complexity,
        "value": sc.value,
        "ready": sc.ready,
        "blocked_by": sc.blocked_by,
        "tags": sc.tags,
        "notes": sc.notes,
    }, indent=2)


def tool_find_refs(args: dict[str, Any]) -> str:
    id_ = int(args["id"])
    pattern = rf"#{id_}\b"
    try:
        result = subprocess.run(
            ["git", "grep", "-nE", pattern],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return f"git grep failed: {e}"
    if result.returncode == 1:
        return f"No references to #{id_} found."
    if result.returncode != 0:
        return f"git grep error (exit {result.returncode}): {result.stderr.strip()}"
    return result.stdout.rstrip()


def tool_list_sections(args: dict[str, Any]) -> str:
    items, _ = _items()
    counts: dict[str, int] = {}
    for it in items:
        if it.archived or it.in_progress:
            continue
        key = it.section + (f" → {it.subsection}" if it.subsection else "")
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return "No open items."
    return "\n".join(f"{n:>4}  {k}" for k, n in sorted(counts.items(), key=lambda x: -x[1]))


def tool_lint(args: dict[str, Any]) -> str:
    skip = bool(args.get("skip_branch_check", False))
    result = lint_file(BACKLOG_PATH, repo_root=REPO_ROOT, skip_branch_check=skip)
    return result.summary()


# ---------- Phase 2 — write tools ------------------------------------------

# Durable monotonic ID high-water mark. DONE items are *deleted* from the
# backlog (not archived), so `max(live ids) + 1` alone can re-issue a retired
# ID once the current top item is closed. The `<!-- next-id: N -->` marker
# persists the high-water mark across deletions; the live max is only a
# self-healing fallback for files that predate the marker.
NEXT_ID_RE = re.compile(r"<!--\s*next-id:\s*(\d+)\s*-->")


def _read_next_id_marker(text: str) -> int | None:
    m = NEXT_ID_RE.search(text)
    return int(m.group(1)) if m else None


def _set_next_id_marker(text: str, value: int) -> str:
    """Write/update the next-id marker, inserting it just below the title if absent."""
    repl = f"<!-- next-id: {value} -->"
    if NEXT_ID_RE.search(text):
        return NEXT_ID_RE.sub(repl, text, count=1)
    head, sep, rest = text.partition("\n")
    return f"{head}\n{repl}\n{rest}" if sep else f"{repl}\n{text}"


def _next_free_id_from_text(text: str) -> int:
    live_max = max((it.id for it in parse_backlog_text(text)), default=0)
    return max(_read_next_id_marker(text) or 0, live_max + 1)


def _next_free_id() -> int:
    return _next_free_id_from_text(BACKLOG_PATH.read_text())


def _verify_with_lint() -> tuple[bool, str]:
    result = lint_file(BACKLOG_PATH, repo_root=REPO_ROOT, skip_branch_check=True)
    return result.ok, result.summary()


def tool_add_item(args: dict[str, Any]) -> str:
    # Items are always written in heading format (`### #NNN [open] title` + body).
    # `section` defaults to "Inbox" — append-only buffer at the bottom of the
    # backlog, periodically curated into topical sections. Mirrors the
    # CHANGELOG-INBOX → CHANGELOG flow. The target section heading must exist;
    # add_item fails closed otherwise.
    section = args.get("section") or "Inbox"
    description = args["description"]
    body = (args.get("body") or "").strip()
    files = (args.get("files") or "").strip()

    text = BACKLOG_PATH.read_text()
    new_id = _next_free_id_from_text(text)

    # `files`, when given, becomes a leading `_Files: …_` line of the body.
    files_line = f"_Files: {files}_\n\n" if files else ""
    body_block = f"{files_line}{body}".strip()
    new_row = f"### #{new_id} [open] {description}\n"
    if body_block:
        new_row += f"\n{body_block}\n"

    if " → " in section:
        _, h2 = section.split(" → ", 1)
        anchor = f"### {h2}"
    else:
        anchor = f"## {section}"

    # Match anchor only at the start of a line to avoid hitting the same text
    # in prose or table cells.
    anchor_re = re.compile(r"^" + re.escape(anchor) + r"(?:\s|$)", re.MULTILINE)
    m = anchor_re.search(text)
    if not m:
        return f"Section heading not found: {anchor!r}"
    idx = m.start()

    rest = text[idx:]
    next_section = re.search(r"\n(?=## |### )", rest[len(anchor):])
    insertion_end = idx + len(anchor) + (
        next_section.start() if next_section else len(rest) - len(anchor)
    )

    # A heading item needs a blank line before and after it so renderers and the
    # lint's heading-flush check stay happy.
    pre = text[:insertion_end].rstrip("\n") + "\n\n"
    suffix = text[insertion_end:].lstrip("\n")
    new_text = pre + new_row.rstrip("\n") + "\n\n" + suffix
    new_text = _set_next_id_marker(new_text, new_id + 1)

    BACKLOG_PATH.write_text(new_text)
    ok, msg = _verify_with_lint()
    if not ok:
        BACKLOG_PATH.write_text(text)
        return f"add_item rolled back; lint failed:\n{msg}"
    return f"Added #{new_id} to {section!r}"


def _delete_table_row(text: str, raw_line: str) -> str:
    for candidate in (raw_line + "\n", raw_line):
        if candidate in text:
            return text.replace(candidate, "", 1)
    return text


def _delete_heading_block(text: str, raw_heading_line: str) -> str:
    idx = text.find(raw_heading_line)
    if idx == -1:
        return text
    end = idx + len(raw_heading_line)
    rest = text[end:]
    m = re.search(r"\n(?=#{2,3} )", rest)
    # m.start() is the \n just before the next heading — don't include it so
    # the blank-line separator before that heading is preserved.
    block_end = end + (m.start() if m else len(rest))
    return text[:idx] + text[block_end:]



def tool_update_status(args: dict[str, Any]) -> str:
    id_ = int(args["id"])
    new_status = args["status"].lower()
    branch = args.get("branch")
    summary = args.get("summary")
    pr = args.get("pr")
    changelog = bool(args.get("changelog", False))

    text = BACKLOG_PATH.read_text()
    _, by_id = _items()
    if id_ not in by_id:
        return f"#{id_} not found"
    it = by_id[id_]

    is_heading = it.raw_line.startswith("### ")
    # description is already clean (status tag stripped by parser for both formats)
    clean_desc = it.description

    if new_status == "in_progress":
        if not branch:
            return "branch is required for status=in_progress"
        if is_heading:
            new_line = f"### #{it.id} [in-progress: {branch}] {clean_desc}"
        else:
            new_line = f"| {it.id} | [in-progress: {branch}] | {it.files} | {clean_desc} |"
        new_text = text.replace(it.raw_line, new_line)
    elif new_status == "done":
        # Done items are deleted from Backlog.md; CHANGELOG-INBOX is the record.
        if is_heading:
            new_text = _delete_heading_block(text, it.raw_line)
        else:
            new_text = _delete_table_row(text, it.raw_line)
    elif new_status == "open":
        if is_heading:
            new_line = f"### #{it.id} [open] {clean_desc}"
        else:
            new_line = f"| {it.id} | [open] | {it.files} | {it.description} |"
        new_text = text.replace(it.raw_line, new_line)
    else:
        return f"unknown status: {new_status!r} (use in_progress / done / open)"

    BACKLOG_PATH.write_text(new_text)
    ok, msg = _verify_with_lint()
    if not ok:
        BACKLOG_PATH.write_text(text)
        return f"update_status rolled back; lint failed:\n{msg}"

    changelog_note = ""
    relocated_note = ""
    if new_status == "done" and changelog and summary:
        if CHANGELOG_INBOX_PATH.is_file():
            pr_ref = f" (PR #{pr})" if pr else ""
            inbox_line = f"- **#{id_}{pr_ref}:** {summary.rstrip('.')}.\n"
            inbox_text = CHANGELOG_INBOX_PATH.read_text()
            marker = "<!-- append new DONE lines below this line -->"
            if marker in inbox_text:
                inbox_text = inbox_text.replace(marker, marker + "\n" + inbox_line.rstrip("\n"), 1)
            else:
                inbox_text = inbox_text.rstrip("\n") + "\n" + inbox_line
            CHANGELOG_INBOX_PATH.write_text(inbox_text)
            changelog_note = "; appended to CHANGELOG-INBOX"
        else:
            changelog_note = "; CHANGELOG-INBOX not found — skipped"

    return f"#{id_} status set to {new_status}{relocated_note}{changelog_note}"


def tool_set_score(args: dict[str, Any]) -> str:
    id_ = int(args["id"])

    if not SCORES_PATH.exists():
        SCORES_PATH.write_text("id,complexity,value,ready,blocked_by,tags,notes\n")

    # Merge against the existing row: a caller updating one field (e.g. just
    # `value`) must not blank the fields it didn't pass. Only keys actually
    # present in `args` override; everything else keeps the stored value.
    existing = parse_scores(SCORES_PATH).get(id_)

    def pick(key: str, current: Any) -> Any:
        return args[key] if key in args else current

    complexity = pick("complexity", existing.complexity if existing else None)
    value = pick("value", existing.value if existing else None)
    ready = pick("ready", existing.ready if existing else "")
    blocked_by = pick("blocked_by", existing.blocked_by if existing else [])
    tags = pick("tags", existing.tags if existing else [])
    notes = pick("notes", existing.notes if existing else "")

    text = SCORES_PATH.read_text()
    lines = text.splitlines(keepends=True)
    header_idx = next(
        (i for i, l in enumerate(lines) if l.startswith("id,") and "complexity" in l),
        None,
    )
    if header_idx is None:
        return "couldn't find CSV header in scores file"

    blocked_str = (
        ",".join(str(b) for b in blocked_by)
        if isinstance(blocked_by, list)
        else str(blocked_by)
    )
    tags_str = ";".join(tags) if isinstance(tags, list) else str(tags)
    # Write through csv so fields containing the column delimiter — notes with a
    # comma, or a multi-value blocked_by like "783,784" — get quoted instead of
    # corrupting the row on the next DictReader parse.
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow([
        id_,
        complexity if complexity is not None else "",
        value if value is not None else "",
        ready or "",
        blocked_str,
        tags_str,
        notes or "",
    ])
    new_row = buf.getvalue() + "\n"

    replaced = False
    for i, line in enumerate(lines):
        if line.startswith(f"{id_},"):
            lines[i] = new_row
            replaced = True
            break
    if not replaced:
        ids_at = [
            (int(l.split(",", 1)[0]), i)
            for i, l in enumerate(lines[header_idx + 1:], start=header_idx + 1)
            if l[:1].isdigit()
        ]
        insert_at = next((idx for nid, idx in ids_at if nid > id_), None)
        if insert_at is None:
            lines.append(new_row)
        else:
            lines.insert(insert_at, new_row)

    SCORES_PATH.write_text("".join(lines))
    return f"score for #{id_}: {'updated' if replaced else 'inserted'}"


# ----------------------------------------------------------------------------
# MCP server wiring
# ----------------------------------------------------------------------------

server = Server("backlog")

TOOLS: list[tuple[str, str, dict, Any]] = [
    (
        "list_items",
        "Filter backlog items. Combine status/section/score/files filters. "
        "Returns one line per match.",
        {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["open", "in_progress", "done", "all"]},
                "section": {"type": "string", "description": "Substring match against section/subsection name — e.g. 'topology' matches '## Epic: Network Topology & Segmentation'. Use list_sections to see available names."},
                "ready": {"type": "string", "enum": ["Y", "N", "partial"]},
                "max_complexity": {"type": "integer", "minimum": 1, "maximum": 5},
                "min_value": {"type": "integer", "minimum": 1, "maximum": 5},
                "tag": {"type": "string"},
                "files": {"type": "string", "description": "Substring match against the files column — e.g. 'src/auth/' to find items touching that path."},
                "limit": {"type": "integer", "default": 50},
            },
        },
        tool_list_items,
    ),
    (
        "get_item",
        "Fetch a single backlog item with full description, files, score, and section.",
        {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
        tool_get_item,
    ),
    (
        "get_score",
        "Fetch the score row for a single item from the scoring CSV.",
        {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
        tool_get_score,
    ),
    (
        "find_refs",
        "Run `git grep` for #<id> across the whole repo. Catches code, docs, "
        "CHANGELOG, commit-message bodies kept as files.",
        {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
        tool_find_refs,
    ),
    (
        "list_sections",
        "List backlog sections with their open-item counts.",
        {"type": "object", "properties": {}},
        tool_list_sections,
    ),
    (
        "lint",
        "Run the hygiene lint and return its findings.",
        {"type": "object", "properties": {"skip_branch_check": {"type": "boolean", "default": False}}},
        tool_lint,
    ),
    (
        "add_item",
        "Create a new backlog item. This is the ONLY way to create items — it "
        "allocates the next free ID atomically (under a file lock) and returns it, "
        "so concurrent callers never collide. Items are written in heading format "
        "(`### #NNN [open] title` followed by an optional markdown body). Defaults to "
        "the `## Inbox` section (append-only buffer; curated into topical sections "
        "later) — pass an explicit `section` only when you're confident which topical "
        "section it belongs in. Put the full design/finding prose in `body` (multi-"
        "paragraph, lists, and code fences are fine); `files` is optional and, when "
        "given, is rendered as a leading `_Files: …_` line. Verifies via lint and "
        "rolls back on failure.",
        {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "Section heading. Defaults to 'Inbox'. Use 'Section → Subsection' for nested.",
                },
                "description": {"type": "string", "description": "Single-line title (rendered after the ID)."},
                "body": {
                    "type": "string",
                    "description": "Optional free-form markdown body — paragraphs, lists, code fences.",
                },
                "files": {"type": "string", "description": "Optional file/path list; rendered as a leading `_Files: …_` line."},
            },
            "required": ["description"],
        },
        tool_add_item,
    ),
    (
        "update_status",
        "Flip an item to in_progress / done / open. For in_progress, branch is required. "
        "For done, set changelog=true and provide summary to append to CHANGELOG-INBOX "
        "(externally-observable changes only — skip for refactors and internal fixes).",
        {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "status": {"type": "string", "enum": ["in_progress", "done", "open"]},
                "branch": {"type": "string"},
                "summary": {"type": "string", "description": "Brief summary for DONE marker and CHANGELOG-INBOX entry"},
                "pr": {"type": "integer", "description": "PR number for CHANGELOG-INBOX entry"},
                "changelog": {"type": "boolean", "description": "Append to CHANGELOG-INBOX (externally-observable changes only)"},
            },
            "required": ["id", "status"],
        },
        tool_update_status,
    ),
    (
        "set_score",
        "Insert or update a row in the scoring CSV. Update merges: only the "
        "fields you pass are changed; omitted fields keep their existing values "
        "(pass `value` alone and complexity/ready/tags/notes are preserved). To "
        "clear a field, pass it explicitly empty.",
        {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "complexity": {"type": "integer", "minimum": 1, "maximum": 5},
                "value": {"type": "integer", "minimum": 1, "maximum": 5},
                "ready": {"type": "string", "enum": ["Y", "N", "partial"]},
                "blocked_by": {"type": "array", "items": {"type": "integer"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "notes": {"type": "string"},
            },
            "required": ["id"],
        },
        tool_set_score,
    ),
]

TOOL_BY_NAME = {name: handler for name, _, _, handler in TOOLS}

# Tools that mutate files on disk — wrapped in an fcntl flock so concurrent
# stdio sessions (and any other process honouring backlog_lock) don't race.
_WRITE_TOOL_NAMES = {"add_item", "update_status", "set_score"}


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return [
        Tool(name=name, description=desc, inputSchema=schema)
        for name, desc, schema, _ in TOOLS
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    handler = TOOL_BY_NAME.get(name)
    if handler is None:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]
    try:
        if name in _WRITE_TOOL_NAMES:
            with backlog_lock(BACKLOG_PATH):
                result = handler(arguments or {})
        else:
            result = handler(arguments or {})
    except Exception as e:
        result = f"{type(e).__name__}: {e}"
    return [TextContent(type="text", text=str(result))]


def run() -> None:
    """Console-script entrypoint: `backlog-mcp`."""
    asyncio.run(_main())


async def _main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    run()
