"""MCP server exposing a markdown-table backlog to agents.

Reads/writes a `Backlog.md` table (and an optional `Backlog-Scores.csv` sidecar)
so MCP-aware agents can list / get / score / add / mark-status without dragging
the whole file into context.

Configuration is environment-driven so the server can serve any project's
backlog without code changes:

    BACKLOG_PATH            Path to the markdown backlog (default: docs/Backlog.md)
    BACKLOG_SCORES          Path to the scoring CSV; optional, scoring tools no-op
                            if unset or missing (default: docs/Backlog-Scores.csv)
    BACKLOG_REPO_ROOT       Repo root for git operations (default: parent of backlog;
                            falls back to `git rev-parse --show-toplevel`)
    BACKLOG_ARCHIVE_PREFIX  Prefix that identifies the archive `## ` heading
                            (default: "Done", matching `## Done — archive`)
    BACKLOG_CHANGELOG_INBOX Path to the CHANGELOG-INBOX append buffer
                            (default: CHANGELOG-INBOX.md at repo root)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .lint import lint_file
from .parser import (
    Item,
    Score,
    index_by_id,
    one_line_summary,
    parse_backlog,
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


BACKLOG_PATH = Path(os.environ.get("BACKLOG_PATH", "docs/Backlog.md")).resolve()
SCORES_PATH = Path(os.environ.get("BACKLOG_SCORES", "docs/Backlog-Scores.csv")).resolve()
ARCHIVE_PREFIX = os.environ.get("BACKLOG_ARCHIVE_PREFIX", "Done")
REPO_ROOT = _resolve_repo_root(BACKLOG_PATH)
CHANGELOG_INBOX_PATH = Path(
    os.environ.get("BACKLOG_CHANGELOG_INBOX", str(REPO_ROOT / "CHANGELOG-INBOX.md"))
).resolve()


def _items() -> tuple[list[Item], dict[int, Item]]:
    items = parse_backlog(BACKLOG_PATH, archive_section_prefix=ARCHIVE_PREFIX)
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

def _next_free_id() -> int:
    items, _ = _items()
    return (max((it.id for it in items), default=0)) + 1


def _verify_with_lint() -> tuple[bool, str]:
    result = lint_file(BACKLOG_PATH, repo_root=REPO_ROOT, skip_branch_check=True)
    return result.ok, result.summary()


def tool_add_item(args: dict[str, Any]) -> str:
    # `section` defaults to "Inbox" — append-only buffer at the bottom of the
    # backlog, periodically curated into topical sections. Mirrors the
    # CHANGELOG-INBOX → CHANGELOG flow. The file must contain a `## Inbox`
    # heading (above the archive); add_item fails closed otherwise.
    section = args.get("section") or "Inbox"
    files = args["files"]
    description = args["description"]

    text = BACKLOG_PATH.read_text()
    new_id = _next_free_id()
    new_row = f"| {new_id} | {files} | {description} |\n"

    if " → " in section:
        _, h2 = section.split(" → ", 1)
        anchor = f"### {h2}"
    else:
        anchor = f"## {section}"

    idx = text.find(anchor)
    if idx == -1:
        return f"Section heading not found: {anchor!r}"

    rest = text[idx:]
    next_section = re.search(r"\n(?=## |### )", rest[len(anchor):])
    insertion_end = idx + len(anchor) + (
        next_section.start() if next_section else len(rest) - len(anchor)
    )

    pre = text[:insertion_end]
    while pre.endswith("\n\n"):
        pre = pre[:-1]
    if not pre.endswith("\n"):
        pre += "\n"
    new_text = pre + new_row + text[insertion_end:].lstrip("\n")

    BACKLOG_PATH.write_text(new_text)
    ok, msg = _verify_with_lint()
    if not ok:
        BACKLOG_PATH.write_text(text)
        return f"add_item rolled back; lint failed:\n{msg}"
    return f"Added #{new_id} to {section!r}"


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

    new_desc = re.sub(r"^\*\*IN PROGRESS \([^)]+\)\*\*\s*", "", it.description)

    if new_status == "in_progress":
        if not branch:
            return "branch is required for status=in_progress"
        new_desc = f"**IN PROGRESS ({branch})** {new_desc}"
        new_line = f"| {it.id} | {it.files} | {new_desc} |"
    elif new_status == "done":
        if not new_desc.lstrip().startswith("**DONE"):
            done_marker = f"**DONE{f' ({summary})' if summary else ''}**"
            new_desc = f"{done_marker} {new_desc}"
        new_line = f"| ~~{it.id}~~ | ~~{it.files}~~ | {new_desc} |"
    elif new_status == "open":
        new_line = f"| {it.id} | {it.files} | {new_desc} |"
    else:
        return f"unknown status: {new_status!r} (use in_progress / done / open)"

    new_text = text.replace(it.raw_line, new_line)
    BACKLOG_PATH.write_text(new_text)
    ok, msg = _verify_with_lint()
    if not ok:
        BACKLOG_PATH.write_text(text)
        return f"update_status rolled back; lint failed:\n{msg}"

    changelog_note = ""
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

    return f"#{id_} status set to {new_status}{changelog_note}"


def tool_set_score(args: dict[str, Any]) -> str:
    id_ = int(args["id"])
    complexity = args.get("complexity")
    value = args.get("value")
    ready = args.get("ready", "")
    blocked_by = args.get("blocked_by", [])
    tags = args.get("tags", [])
    notes = args.get("notes", "")

    if not SCORES_PATH.exists():
        SCORES_PATH.write_text("id,complexity,value,ready,blocked_by,tags,notes\n")

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
    new_row = (
        f"{id_},{complexity if complexity is not None else ''},"
        f"{value if value is not None else ''},{ready},{blocked_str},{tags_str},{notes}\n"
    )

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
        "Filter backlog items. Combine status/section/score filters. "
        "Returns one line per match.",
        {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["open", "in_progress", "done", "all"]},
                "section": {"type": "string"},
                "ready": {"type": "string", "enum": ["Y", "N", "partial"]},
                "max_complexity": {"type": "integer", "minimum": 1, "maximum": 5},
                "min_value": {"type": "integer", "minimum": 1, "maximum": 5},
                "tag": {"type": "string"},
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
        "Create a new backlog item with the next free ID. Defaults to the `## Inbox` "
        "section (append-only buffer; curated into topical sections later). Pass an "
        "explicit `section` only if you're confident which topical section it belongs "
        "in. Verifies via lint and rolls back on failure.",
        {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "Section heading. Defaults to 'Inbox'. Use 'Section → Subsection' for nested.",
                },
                "files": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["files", "description"],
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
        "Insert or update a row in the scoring CSV.",
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
