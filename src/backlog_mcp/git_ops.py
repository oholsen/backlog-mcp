from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def commit_and_push(
    repo_root: Path,
    message: str,
    paths: list[Path] | None = None,
) -> None:
    """Stage, commit, and push. If `paths` is given, only those paths are staged
    (missing entries are skipped). If `paths` is None, falls back to `git add -A`
    — legacy behaviour, racy when concurrent writes to the repo are possible.

    Guards against empty commits: if nothing is staged after `git add`, logs and
    returns without invoking `git commit` (which would otherwise fail with
    `CalledProcessError`).
    """
    if paths is None:
        subprocess.run(["git", "add", "-A"], cwd=repo_root, check=True, capture_output=True)
    else:
        existing = [p for p in paths if p.exists()]
        if existing:
            args = ["git", "add", "--"] + [str(p) for p in existing]
            subprocess.run(args, cwd=repo_root, check=True, capture_output=True)

    # Empty-commit guard: if our write was already swept into a concurrent
    # writer's commit, there's nothing left to commit.
    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=repo_root,
        capture_output=True,
    )
    if diff.returncode == 0:
        logger.info("no staged changes; skipping commit (%s)", message)
        return

    subprocess.run(["git", "commit", "-m", message], cwd=repo_root, check=True, capture_output=True)
    try:
        subprocess.run(["git", "push"], cwd=repo_root, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        logger.warning("git push failed (changes committed locally): %s", e.stderr.decode())
