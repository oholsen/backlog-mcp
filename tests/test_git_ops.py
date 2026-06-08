"""Tests for commit_and_push: narrow staging + empty-commit guard."""

from __future__ import annotations

import subprocess
from pathlib import Path

from backlog_mcp.git_ops import commit_and_push


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, check=check, capture_output=True, text=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "seed.md").write_text("seed\n")
    _git(repo, "add", "seed.md")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def test_commit_and_push_narrow_staging(tmp_path):
    """With `paths=[A]`, a modification to B must NOT be staged."""
    repo = _init_repo(tmp_path)
    a = repo / "Backlog.md"
    b = repo / "Other.md"
    a.write_text("A change\n")
    b.write_text("B change\n")

    commit_and_push(repo, "test: only A", paths=[a])

    # Last commit should contain only Backlog.md
    files = _git(repo, "show", "--name-only", "--format=", "HEAD").stdout.strip().splitlines()
    assert files == ["Backlog.md"], files
    # B is still unstaged
    status = _git(repo, "status", "--porcelain").stdout
    assert "Other.md" in status


def test_commit_and_push_skips_empty_commit(tmp_path):
    """If staging yields no diff, no commit is created."""
    repo = _init_repo(tmp_path)
    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()

    # No modifications. Narrow staging picks nothing up.
    commit_and_push(repo, "test: nothing", paths=[repo / "Backlog.md"])

    head_after = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert head_before == head_after, "HEAD must not advance when nothing is staged"


def test_commit_and_push_skips_missing_paths(tmp_path):
    """`paths` entries that don't exist are silently skipped (don't error)."""
    repo = _init_repo(tmp_path)
    a = repo / "Backlog.md"
    a.write_text("A change\n")
    missing = repo / "does-not-exist.csv"

    # Missing path must not raise.
    commit_and_push(repo, "test: a only", paths=[a, missing])

    files = _git(repo, "show", "--name-only", "--format=", "HEAD").stdout.strip().splitlines()
    assert files == ["Backlog.md"]
