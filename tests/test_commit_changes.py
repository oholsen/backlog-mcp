"""Tests for commit_changes: hunk-safe autocommit that never sweeps concurrent
unstaged edits in the same file."""

from __future__ import annotations

import subprocess
from pathlib import Path

from backlog_mcp.git_ops import commit_changes


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, check=check, capture_output=True, text=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    return repo


def _seed(repo: Path, name: str, content: str) -> Path:
    p = repo / name
    p.write_text(content)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"seed {name}")
    return p


def _head_blob(repo: Path, rel: str) -> str:
    return _git(repo, "show", f"HEAD:{rel}").stdout


def test_clean_tree_commits_only_our_change(tmp_path):
    """When the file was clean vs HEAD, our before->after change is committed."""
    repo = _init_repo(tmp_path)
    head = "alpha\nbeta\ngamma\n"
    p = _seed(repo, "Backlog.md", head)
    before = head  # clean working tree
    after = "alpha\nbeta\ngamma\nOURITEM\n"
    p.write_text(after)

    status = commit_changes(repo, [(p, before, after)], "backlog: add_item", push=False)

    assert "committed" in status, status
    assert _head_blob(repo, "Backlog.md") == after
    # Index clean, working tree clean (our change is now HEAD).
    assert _git(repo, "diff", "--cached", "--quiet", check=False).returncode == 0
    assert _git(repo, "status", "--porcelain").stdout.strip() == ""


def test_concurrent_edit_in_same_file_not_swept(tmp_path):
    """The core guarantee: a concurrent unstaged edit in Backlog.md must NOT be
    committed, while our own before->after hunk IS."""
    repo = _init_repo(tmp_path)
    head = "alpha\nbeta\ngamma\n"
    p = _seed(repo, "Backlog.md", head)

    # A concurrent session inserted a line in the middle (unstaged).
    before = "alpha\nCONCURRENT\nbeta\ngamma\n"
    # Our locked write appends an item at the end.
    after = "alpha\nCONCURRENT\nbeta\ngamma\nOURITEM\n"
    p.write_text(after)

    status = commit_changes(repo, [(p, before, after)], "backlog: add_item", push=False)

    assert "committed" in status, status
    # HEAD got ONLY our item — the concurrent line was not swept in.
    committed = _head_blob(repo, "Backlog.md")
    assert "OURITEM" in committed
    assert "CONCURRENT" not in committed
    assert committed == "alpha\nbeta\ngamma\nOURITEM\n"
    # The concurrent edit survives, unstaged, in the working tree.
    assert p.read_text() == after
    assert "CONCURRENT" in p.read_text()
    status_porcelain = _git(repo, "status", "--porcelain").stdout
    assert "Backlog.md" in status_porcelain  # still dirty (the concurrent line)
    # Nothing left staged.
    assert _git(repo, "diff", "--cached", "--quiet", check=False).returncode == 0


def test_dirty_index_guard_skips_commit(tmp_path):
    """If the index already has staged changes, commit_changes refuses (so it
    can't fold pre-staged concurrent work into our commit)."""
    repo = _init_repo(tmp_path)
    head = "alpha\nbeta\n"
    p = _seed(repo, "Backlog.md", head)
    other = repo / "Other.md"
    other.write_text("staged concurrent work\n")
    _git(repo, "add", "Other.md")  # pre-staged by another session
    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()

    after = "alpha\nbeta\nOURITEM\n"
    p.write_text(after)
    status = commit_changes(repo, [(p, head, after)], "backlog: add_item", push=False)

    assert "skipped" in status and "index" in status, status
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == head_before


def test_conflicting_concurrent_edit_is_skipped_not_forced(tmp_path):
    """If a concurrent edit overlaps our edit (merge conflict), the file is left
    unstaged rather than force-committed."""
    repo = _init_repo(tmp_path)
    head = "alpha\nbeta\ngamma\n"
    p = _seed(repo, "Backlog.md", head)
    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()

    # Concurrent edit and our edit both rewrite the same line -> conflict.
    before = "alpha\nBETA_CONCURRENT\ngamma\n"
    after = "alpha\nBETA_OURS\ngamma\n"
    p.write_text(after)

    status = commit_changes(repo, [(p, before, after)], "backlog: update_status", push=False)

    assert "skipped" in status and "conflict" in status, status
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    # Working tree untouched (still our 'after'); nothing staged.
    assert p.read_text() == after
    assert _git(repo, "diff", "--cached", "--quiet", check=False).returncode == 0


def test_new_file_is_added(tmp_path):
    """A file created by the write (absent at HEAD) is staged via --add."""
    repo = _init_repo(tmp_path)
    _seed(repo, "Backlog.md", "alpha\n")  # need at least one commit for HEAD
    newp = repo / "Backlog-Scores.csv"
    after = "id,score\n1,5\n"
    newp.write_text(after)

    status = commit_changes(repo, [(newp, "", after)], "backlog: set_score", push=False)

    assert "committed" in status, status
    assert _head_blob(repo, "Backlog-Scores.csv") == after


def test_no_change_is_noop(tmp_path):
    """before == after for every path -> nothing committed."""
    repo = _init_repo(tmp_path)
    p = _seed(repo, "Backlog.md", "alpha\n")
    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()

    status = commit_changes(repo, [(p, "alpha\n", "alpha\n")], "backlog: noop", push=False)

    assert "skipped" in status, status
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == head_before
