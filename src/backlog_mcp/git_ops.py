from __future__ import annotations

import logging
import subprocess
import tempfile
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


# ---------------------------------------------------------------------------
# Hunk-safe autocommit
#
# `commit_and_push` stages whole files, so on a working tree that already
# carries *concurrent* unstaged edits (another session editing Backlog.md, an
# operator mid-curation) it sweeps those edits into the backlog commit. The
# functions below commit ONLY the `before`->`after` hunks captured around a
# single locked write, applying them on top of HEAD and leaving every
# concurrent edit unstaged and untouched.
# ---------------------------------------------------------------------------


def _git(repo_root: Path, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        input=input_text,
        capture_output=True,
        text=True,
    )


def _index_has_staged_changes(repo_root: Path) -> bool:
    """True if the index already differs from HEAD (something is staged)."""
    return _git(repo_root, "diff", "--cached", "--quiet").returncode != 0


def _head_blob(repo_root: Path, rel: str) -> str | None:
    """Contents of `rel` at HEAD, or None if the path is not tracked at HEAD."""
    cp = _git(repo_root, "show", f"HEAD:{rel}")
    return cp.stdout if cp.returncode == 0 else None


def _stage_only_our_change(
    repo_root: Path, rel: str, before: str, after: str, head: str
) -> bool:
    """Stage exactly the `before`->`after` hunks for `rel`, applied on top of
    HEAD, discarding any concurrent (HEAD->before) edits — without touching the
    working tree.

    Implemented as a 3-way merge with ours=`after` (our edit), base=`before`,
    theirs=`head`. The merge keeps our (base->ours) change *and* the
    (base->theirs) change that removes the concurrent edits, yielding
    head+our-change. The merged blob is written to the object store and placed
    in the index via `update-index`, so neither the working tree nor other index
    entries are disturbed.

    Returns False (staging nothing) if the merge conflicts — i.e. a concurrent
    edit overlaps ours — so the caller leaves the change unstaged rather than
    guess which side wins.
    """
    with tempfile.TemporaryDirectory() as td:
        ours = Path(td) / "ours"
        base = Path(td) / "base"
        theirs = Path(td) / "theirs"
        ours.write_text(after)
        base.write_text(before)
        theirs.write_text(head)
        # `-p` prints the merge to stdout instead of editing `ours` in place.
        merged = subprocess.run(
            ["git", "merge-file", "-p", str(ours), str(base), str(theirs)],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        # returncode: 0 = clean merge, >0 = number of conflicts, <0 = error.
        if merged.returncode != 0:
            return False
        blob = _git(repo_root, "hash-object", "-w", "--stdin", input_text=merged.stdout)
        if blob.returncode != 0:
            return False
        sha = blob.stdout.strip()
        upd = _git(repo_root, "update-index", "--add", "--cacheinfo", f"100644,{sha},{rel}")
        return upd.returncode == 0


def commit_changes(
    repo_root: Path,
    changes: list[tuple[Path, str, str]],
    message: str,
    push: bool = True,
) -> str:
    """Commit ONLY the supplied `before`->`after` hunks, never sweeping
    concurrent unstaged edits in the same files.

    `changes` is a list of `(path, before_text, after_text)` captured around a
    single locked write. For each entry whose text actually changed, the
    before->after hunks are staged on top of HEAD via a 3-way merge (see
    `_stage_only_our_change`); concurrent edits already present in the working
    file stay unstaged and untouched.

    Safety guards:
      * if the index already has staged changes, returns without committing —
        committing would otherwise fold pre-staged concurrent work into our
        commit;
      * a file whose hunks conflict with concurrent edits is skipped (left
        unstaged) and reported, never force-committed;
      * empty-commit guard (nothing staged -> no commit); a failed `git push`
        leaves the commit local.

    Returns a short status string for logging/telemetry.
    """
    if _index_has_staged_changes(repo_root):
        return "skipped: index already has staged changes"

    root = Path(repo_root).resolve()
    staged: list[str] = []
    skipped: list[str] = []
    for path, before, after in changes:
        if before == after:
            continue
        rel = str(Path(path).resolve().relative_to(root))
        head = _head_blob(repo_root, rel)
        if _stage_only_our_change(repo_root, rel, before, after, head or ""):
            staged.append(rel)
        else:
            skipped.append(rel)

    if not staged:
        return (
            f"skipped: nothing staged (conflicts: {skipped})"
            if skipped
            else "skipped: no changes"
        )

    commit = _git(repo_root, "commit", "-m", message)
    if commit.returncode != 0:
        return f"commit failed: {commit.stderr.strip()}"

    pushed = ""
    if push:
        pr = _git(repo_root, "push")
        if pr.returncode == 0:
            pushed = " pushed"
        else:
            pushed = " (push failed; committed locally)"
            logger.warning("git push failed (changes committed locally): %s", pr.stderr.strip())

    status = f"committed {staged}{pushed}"
    if skipped:
        status += f"; left unstaged due to concurrent-edit conflict: {skipped}"
    return status
