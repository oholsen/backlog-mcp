"""Backlog markdown table parser + scoring CSV reader.

No I/O of its own beyond `Path.read_text()` — pure functions over the contents
so the tests can drive parsing from string fixtures.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

ROW_RE = re.compile(r"^\| (\d+) \| (\[[^\]]+\]) \| (.*?) \| (.*) \|$")
HEADING_ITEM_RE = re.compile(r"^### #(\d+)\s+(.*\S)\s*$")


@dataclass
class Item:
    id: int
    files: str
    description: str
    section: str            # `## ` heading
    subsection: str | None  # `### ` heading, if any
    archived: bool          # status tag starts with `[done`
    in_progress: bool       # status tag starts with `[in-progress`
    raw_line: str           # original markdown row (for verifying writes)
    body: str = ""          # heading-format items only: free-form markdown body
                            # between the `### #NNN ...` line and the next boundary


@dataclass
class Score:
    id: int
    complexity: int | None = None
    value: int | None = None
    ready: str = ""
    blocked_by: list[int] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    notes: str = ""


def parse_backlog_text(text: str) -> list[Item]:
    """Parse a backlog markdown file (as text) into a list of Items."""
    items: list[Item] = []
    section: str = ""
    subsection: str | None = None
    body_buf: list[str] | None = None  # collecting body for the last heading-format item

    def flush_body() -> None:
        nonlocal body_buf
        if body_buf is None or not items:
            body_buf = None
            return
        b = list(body_buf)
        while b and not b[0].strip():
            b.pop(0)
        while b and not b[-1].strip():
            b.pop()
        if b:
            items[-1].body = "\n".join(b)
        body_buf = None

    for line in text.splitlines():
        if line.startswith("## "):
            flush_body()
            section = line[3:].strip()
            subsection = None
            continue
        if line.startswith("### "):
            flush_body()
            hm = HEADING_ITEM_RE.match(line)
            if hm:
                hm_full = hm.group(2).strip()
                hm_status = re.match(r"(\[[^\]]+\])\s*(.*)", hm_full)
                if hm_status:
                    status_tag, clean_title = hm_status.group(1), hm_status.group(2)
                else:
                    status_tag, clean_title = "[open]", hm_full
                items.append(Item(
                    id=int(hm.group(1)),
                    files="",
                    description=clean_title,
                    section=section,
                    subsection=subsection,
                    archived=status_tag.startswith("[done"),
                    in_progress=status_tag.startswith("[in-progress"),
                    raw_line=line,
                ))
                body_buf = []
                continue
            subsection = line[4:].strip()
            continue
        m = ROW_RE.match(line)
        if m:
            flush_body()
            id_ = int(m.group(1))
            status_tag = m.group(2)
            files = m.group(3).strip()
            description = m.group(4).strip()
            row_archived = status_tag.startswith("[done")
            row_in_progress = status_tag.startswith("[in-progress")
            items.append(Item(
                id=id_,
                files=files,
                description=description,
                section=section,
                subsection=subsection,
                archived=row_archived,
                in_progress=row_in_progress,
                raw_line=line,
            ))
            continue
        # Treat any line starting with `|` (table header / separator / malformed row)
        # as a table-zone boundary that ends body collection.
        if line.startswith("|"):
            flush_body()
            continue
        if body_buf is not None:
            body_buf.append(line)
    flush_body()
    return items


def parse_backlog(path: Path) -> list[Item]:
    return parse_backlog_text(path.read_text())


def parse_scores_text(text: str) -> dict[int, Score]:
    """Parse the scoring CSV (as text). Lines starting with `#` are comments."""
    out: dict[int, Score] = {}
    rows = (line for line in io.StringIO(text) if not line.lstrip().startswith("#"))
    reader = csv.DictReader(rows)
    for row in reader:
        try:
            id_ = int(row["id"])
        except (ValueError, KeyError, TypeError):
            continue

        def to_int(x: str | None) -> int | None:
            try:
                return int(x) if x else None
            except (ValueError, TypeError):
                return None

        blocked_by = [int(t) for t in (row.get("blocked_by") or "").split(",") if t.strip().isdigit()]
        tags = [t.strip() for t in (row.get("tags") or "").split(";") if t.strip()]
        out[id_] = Score(
            id=id_,
            complexity=to_int(row.get("complexity")),
            value=to_int(row.get("value")),
            ready=(row.get("ready") or "").strip(),
            blocked_by=blocked_by,
            tags=tags,
            notes=(row.get("notes") or "").strip(),
        )
    return out


def parse_scores(path: Path | None) -> dict[int, Score]:
    if path is None or not path.exists():
        return {}
    return parse_scores_text(path.read_text())


def index_by_id(items: list[Item]) -> dict[int, Item]:
    by_id: dict[int, Item] = {}
    for it in items:
        by_id[it.id] = it  # last-wins; lint catches duplicates separately
    return by_id


def one_line_summary(description: str, max_chars: int = 120) -> str:
    """First **bold** chunk or first sentence, capped to max_chars."""
    desc = re.sub(r"^\[[^\]]+\]\s*", "", description)  # strip [status] prefix
    bold = re.match(r"\*\*([^*]+)\*\*", desc)
    if bold:
        s = bold.group(1).strip().rstrip(".")
    else:
        s = desc.split(". ")[0].strip().rstrip(".")
    if len(s) > max_chars:
        s = s[: max_chars - 1] + "…"
    return s
