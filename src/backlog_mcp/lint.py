"""Backlog hygiene lint — pure-Python port of the original bash script.

Four checks:
  1. Duplicate IDs across the whole file (open + archive)
  2. Unresolved git merge-conflict markers
  3. Unclosed table rows (blank line inside a cell breaks the parser)
  4. Stale `IN PROGRESS (branch-name)` markers where the branch no longer
     exists on origin (typically a merged-and-deleted PR)

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

    def summary(self) -> str:
        if self.ok:
            return "OK"
        lines = []
        if self.errors:
            lines.append(f"FAIL: {len(self.errors)} error(s)")
            lines.extend(f"  • {e}" for e in self.errors)
        if self.warnings:
            lines.append(f"warnings: {len(self.warnings)}")
            lines.extend(f"  • {w}" for w in self.warnings)
        return "\n".join(lines)


_ROW_ID = re.compile(r"^\| (~?~?)(\d+)\1 \|")
_CONFLICT = re.compile(r"^(<<<<<<<|=======|>>>>>>>)")
_INPROGRESS = re.compile(r"IN PROGRESS \(([^)]+)\)")
_RESERVED_BRANCHES = {"main", "master", "HEAD"}


def lint_file(
    backlog_path: Path,
    repo_root: Path | None = None,
    skip_branch_check: bool = False,
) -> LintResult:
    if not backlog_path.is_file():
        return LintResult(ok=False, errors=[f"backlog file not readable: {backlog_path}"])

    text = backlog_path.read_text()
    lines = text.splitlines()
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Duplicate IDs
    ids: dict[int, list[int]] = {}  # id -> list of line numbers
    for ln, line in enumerate(lines, start=1):
        m = _ROW_ID.match(line)
        if m:
            ids.setdefault(int(m.group(2)), []).append(ln)
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

    return LintResult(ok=not errors, errors=errors, warnings=warnings)


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
    args = parser.parse_args()

    result = lint_file(
        backlog_path=Path(args.backlog),
        repo_root=Path(args.repo_root) if args.repo_root else None,
        skip_branch_check=args.skip_branch_check,
    )
    print(result.summary())
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
