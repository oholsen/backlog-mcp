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

ROW_RE = re.compile(r"^\| (~~)?(\d+)(~~)? \| (.*?) \| (.*) \|$")


@dataclass
class Item:
    id: int
    files: str
    description: str
    section: str            # `## ` heading
    subsection: str | None  # `### ` heading, if any
    archived: bool          # under a `## Done` (or similar archive) section
    in_progress: bool       # `**IN PROGRESS (...)**` prefix in description
    raw_line: str           # original markdown row (for verifying writes)


@dataclass
class Score:
    id: int
    complexity: int | None = None
    value: int | None = None
    ready: str = ""
    blocked_by: list[int] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    notes: str = ""


def parse_backlog_text(text: str, archive_section_prefix: str = "Done") -> list[Item]:
    """Parse a backlog markdown file (as text) into a list of Items.

    `archive_section_prefix` matches the start of the `## ` heading that holds
    the DONE archive (default: `## Done — archive`, but also matches anything
    starting with `Done`).
    """
    items: list[Item] = []
    section: str = ""
    subsection: str | None = None
    archived = False
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            subsection = None
            archived = section.startswith(archive_section_prefix)
            continue
        if line.startswith("### "):
            subsection = line[4:].strip()
            continue
        m = ROW_RE.match(line)
        if not m:
            continue
        id_ = int(m.group(2))
        files = m.group(4).replace("~~", "").strip()
        description = m.group(5).strip()
        in_progress = "IN PROGRESS" in description and not archived
        items.append(Item(
            id=id_,
            files=files,
            description=description,
            section=section,
            subsection=subsection,
            archived=archived,
            in_progress=in_progress,
            raw_line=line,
        ))
    return items


def parse_backlog(path: Path, archive_section_prefix: str = "Done") -> list[Item]:
    return parse_backlog_text(path.read_text(), archive_section_prefix=archive_section_prefix)


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
    desc = re.sub(r"^\*\*(IN PROGRESS \([^)]+\)|DONE[^*]*)\*\*\s*", "", description)
    bold = re.match(r"\*\*([^*]+)\*\*", desc)
    if bold:
        s = bold.group(1).strip().rstrip(".")
    else:
        s = desc.split(". ")[0].strip().rstrip(".")
    if len(s) > max_chars:
        s = s[: max_chars - 1] + "…"
    return s
