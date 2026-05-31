"""Backlog hygiene lint — pure-Python port of the original bash script.

Checks:
  1. Duplicate IDs across the whole file (open + archive)
  2. Unresolved git merge-conflict markers
  3. Unclosed table rows (blank line inside a cell breaks the parser)
  4. Stale `IN PROGRESS (branch-name)` markers where the branch no longer
     exists on origin (typically a merged-and-deleted PR)
  5. Blank lines inside a table (splits it visually for renderers; `--fix` removes)
  6. Heading flush against a prior table row (needs a blank line; `--fix` inserts)
  7. Stray table rows with no header / separator above them in the section
     (warning only — auto-fix is too invasive)

Cross-reference checking is deferred — the prose mixes "(PRs #X, #Y)" groups,
"Agents.md #6" anchors, and "the #1 finding" with real refs; needs a smarter
parser than is currently warranted.

Returns a structured dict so callers (CLI, MCP server) can render or pipe.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LintResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fixed: int = 0  # count of issues auto-fixed when fix=True

    def summary(self) -> str:
        lines: list[str] = []
        if self.fixed:
            lines.append(f"fixed: {self.fixed} issue(s)")
        if self.errors:
            lines.append(f"FAIL: {len(self.errors)} error(s)")
            lines.extend(f"  • {e}" for e in self.errors)
        if self.warnings:
            lines.append(f"warnings: {len(self.warnings)}")
            lines.extend(f"  • {w}" for w in self.warnings)
        if not lines:
            return "OK"
        if self.ok and not self.warnings:
            lines.append("OK")
        return "\n".join(lines)


_ROW_ID = re.compile(r"^\| (\d+) \| \[")  # matches new 4-col format: | NNN | [status] |
_TABLE_HEADER = re.compile(r"^\|\s*#\s*\|", re.IGNORECASE)
_TABLE_SEP = re.compile(r"^\|[\s\-:|]+\|\s*$")
_CONFLICT = re.compile(r"^(<<<<<<<|=======|>>>>>>>)")
_INPROGRESS = re.compile(r"\[in-progress: ([^\]]+)\]")
_RESERVED_BRANCHES = {"main", "master", "HEAD"}


def _is_table_line(line: str) -> bool:
    """True for any line that's part of a table (row, header, or separator)."""
    return bool(_ROW_ID.match(line) or _TABLE_HEADER.match(line) or _TABLE_SEP.match(line))


def lint_file(
    backlog_path: Path,
    repo_root: Path | None = None,
    skip_branch_check: bool = False,
    fix: bool = False,
) -> LintResult:
    if not backlog_path.is_file():
        return LintResult(ok=False, errors=[f"backlog file not readable: {backlog_path}"])

    text = backlog_path.read_text()
    if fix:
        text, fixed_count = _autofix(text)
        if fixed_count:
            backlog_path.write_text(text)
    else:
        fixed_count = 0
    lines = text.splitlines()
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Duplicate IDs
    ids: dict[int, list[int]] = {}  # id -> list of line numbers
    for ln, line in enumerate(lines, start=1):
        m = _ROW_ID.match(line)
        if m:
            ids.setdefault(int(m.group(1)), []).append(ln)
    dupes = {id_: lns for id_, lns in ids.items() if len(lns) > 1}
    if dupes:
        for id_, lns in sorted(dupes.items()):
            errors.append(f"duplicate ID #{id_} on lines {', '.join(str(l) for l in lns)}")

    # 2. Conflict markers
    for ln, line in enumerate(lines, start=1):
        if _CONFLICT.match(line):
            errors.append(f"unresolved conflict marker on line {ln}: {line.strip()[:60]}")

    # 3. Multi-line table rows — a blank line immediately after a row that doesn't
    #    close with | means the cell content spills across lines, breaking the parser.
    for ln, line in enumerate(lines, start=1):
        if _ROW_ID.match(line) and not line.rstrip().endswith("|"):
            errors.append(
                f"unclosed table row on line {ln} (blank line inside cell?): "
                f"{line.strip()[:60]}…"
            )

    # 5/6/7. Structural shape: blank-in-table, heading-flush-against-row, header-missing.
    for ln in range(1, len(lines) + 1):
        line = lines[ln - 1]
        prev = lines[ln - 2] if ln >= 2 else ""
        nxt = lines[ln] if ln < len(lines) else ""

        # 5. Blank line between two table lines in the same section.
        if line == "" and _is_table_line(prev) and _is_table_line(nxt):
            warnings.append(f"blank line inside table on line {ln} (use --fix to remove)")

        # 6. Heading immediately after a table row (no blank-line separator).
        if (line.startswith("## ") or line.startswith("### ")) and _is_table_line(prev):
            warnings.append(
                f"heading on line {ln} flush against prior table row (use --fix to insert blank)"
            )

    # 7. Section-local: rows present with no header/separator anywhere above them
    #    in the current section. Walk per-section.
    section_start_ln = 0  # 0 means "haven't entered any section yet"
    section_has_header = False
    section_has_separator = False
    section_first_row_ln: int | None = None
    section_label = ""

    def _flush_section_check():
        nonlocal section_first_row_ln, section_has_header, section_has_separator, section_label
        if section_first_row_ln is not None and not (section_has_header and section_has_separator):
            missing = []
            if not section_has_header:
                missing.append("header")
            if not section_has_separator:
                missing.append("separator")
            warnings.append(
                f"section {section_label!r} first table row on line {section_first_row_ln} "
                f"is missing {'/'.join(missing)} (table won't render; not auto-fixed)"
            )
        section_first_row_ln = None
        section_has_header = False
        section_has_separator = False

    for ln, line in enumerate(lines, start=1):
        if line.startswith("## ") or line.startswith("### "):
            _flush_section_check()
            section_label = line.lstrip("# ").strip()
            section_start_ln = ln
            continue
        if _TABLE_HEADER.match(line):
            section_has_header = True
        elif _TABLE_SEP.match(line):
            section_has_separator = True
        elif _ROW_ID.match(line) and section_first_row_ln is None:
            section_first_row_ln = ln
    _flush_section_check()

    # 4. Stale IN PROGRESS markers
    if not skip_branch_check:
        if repo_root is None:
            repo_root = backlog_path.parent.parent  # best-effort default
        markers: dict[str, list[int]] = {}
        for ln, line in enumerate(lines, start=1):
            for m in _INPROGRESS.finditer(line):
                token = m.group(1).split(",")[0].strip()
                if not token or token in _RESERVED_BRANCHES:
                    continue
                markers.setdefault(token, []).append(ln)
        if markers:
            try:
                subprocess.run(
                    ["git", "fetch", "--prune", "origin"],
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                for branch in sorted(markers):
                    rc = subprocess.run(
                        ["git", "show-ref", "--verify", "--quiet",
                         f"refs/remotes/origin/{branch}"],
                        cwd=repo_root,
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )
                    if rc.returncode != 0:
                        lns = markers[branch]
                        errors.append(
                            f"IN PROGRESS marker for branch '{branch}' — not on origin "
                            f"(used on {len(lns)} item(s) at lines {', '.join(str(l) for l in lns[:5])}"
                            f"{'…' if len(lns) > 5 else ''})"
                        )
            except (FileNotFoundError, subprocess.TimeoutExpired) as e:
                warnings.append(f"branch check skipped: {e}")
    else:
        warnings.append("branch check skipped (skip_branch_check=True)")

    return LintResult(ok=not errors, errors=errors, warnings=warnings, fixed=fixed_count)


def _autofix(text: str) -> tuple[str, int]:
    """Apply safe structural repairs. Returns (new_text, count_of_fixes)."""
    lines = text.splitlines()
    out: list[str] = []
    fixed = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        # Drop a blank line sitting between two table lines.
        if (
            line == ""
            and out and _is_table_line(out[-1])
            and i + 1 < len(lines) and _is_table_line(lines[i + 1])
        ):
            fixed += 1
            i += 1
            continue
        # Insert a blank line before a heading flush against the prior row.
        if (
            (line.startswith("## ") or line.startswith("### "))
            and out and _is_table_line(out[-1])
        ):
            out.append("")
            fixed += 1
        out.append(line)
        i += 1

    new_text = "\n".join(out)
    if text.endswith("\n") and not new_text.endswith("\n"):
        new_text += "\n"
    return new_text, fixed


def main() -> int:
    """Console-script entrypoint: `backlog-lint`."""
    import argparse

    parser = argparse.ArgumentParser(description="Backlog hygiene lint")
    parser.add_argument(
        "--backlog",
        default=os.environ.get("BACKLOG_PATH", "Backlog.md"),
        help="path to Backlog.md (default: $BACKLOG_PATH or Backlog.md)",
    )
    parser.add_argument(
        "--repo-root",
        default=os.environ.get("BACKLOG_REPO_ROOT"),
        help="repo root for git checks (default: $BACKLOG_REPO_ROOT or backlog parent dir)",
    )
    parser.add_argument(
        "--skip-branch-check",
        action="store_true",
        default=os.environ.get("SKIP_BRANCH_CHECK") == "1",
        help="skip stale-IN-PROGRESS-marker check (no network)",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="auto-repair safe shape issues (blank-in-table, heading-flush)",
    )
    args = parser.parse_args()

    result = lint_file(
        backlog_path=Path(args.backlog),
        repo_root=Path(args.repo_root) if args.repo_root else None,
        skip_branch_check=args.skip_branch_check,
        fix=args.fix,
    )
    print(result.summary())
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
