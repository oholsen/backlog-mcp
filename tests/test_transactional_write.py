"""Tests for sync_to_origin / _push / transactional_write.

These exercise the transactional write path against a real bare `origin`
remote and a second clone acting as a concurrent writer, so the push-race
re-apply / ID re-mint behaviour is verified end-to-end.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from backlog_mcp import git_ops
from backlog_mcp.git_ops import _push, sync_to_origin, transactional_write

SEED = "# Backlog\n\n<!-- next-id: 1 -->\n\n## Inbox\n"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, check=check, capture_output=True, text=True)


def _config(repo: Path) -> None:
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "commit.gpgsign", "false")


def _origin_and_clones(tmp_path: Path, n: int = 1) -> tuple[Path, list[Path]]:
    """Bare `origin` seeded with SEED, plus `n` working clones on branch main."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "-q", str(origin), str(seed))
    _config(seed)
    (seed / "Backlog.md").write_text(SEED)
    _git(seed, "add", "Backlog.md")
    _git(seed, "commit", "-q", "-m", "seed")
    _git(seed, "push", "-q", "origin", "main")
    clones = []
    for i in range(n):
        c = tmp_path / f"clone{i}"
        _git(tmp_path, "clone", "-q", str(origin), str(c))
        _config(c)
        clones.append(c)
    return origin, clones


def _add_apply(path: Path):
    """An apply_fn mimicking add_item: allocate from the next-id marker, append
    the item, bump the marker. Re-reads the file each call, so a re-sync between
    calls makes it re-mint."""

    def _apply() -> tuple[bool, str]:
        text = path.read_text()
        n = int(re.search(r"next-id:\s*(\d+)", text).group(1))
        text = re.sub(r"next-id:\s*\d+", f"next-id: {n + 1}", text)
        text = text.rstrip("\n") + f"\n\n### #{n} [open] item {n}\n"
        path.write_text(text)
        return True, f"added #{n}"

    return _apply


def _ids_on_origin(origin: Path, tmp_path: Path) -> list[int]:
    out = _git(tmp_path, "clone", "-q", str(origin), str(tmp_path / "verify"))
    text = (tmp_path / "verify" / "Backlog.md").read_text()
    subprocess.run(["rm", "-rf", str(tmp_path / "verify")], check=True)
    return sorted(int(m) for m in re.findall(r"^### #(\d+) ", text, re.MULTILINE))


def test_sync_then_commit_and_push(tmp_path):
    origin, [repo] = _origin_and_clones(tmp_path)
    result, status = transactional_write(
        repo, [repo / "Backlog.md"], _add_apply(repo / "Backlog.md"), "backlog: add_item"
    )
    assert result == "added #1"
    assert "pushed" in status, status
    assert _ids_on_origin(origin, tmp_path) == [1]


def test_push_race_reapplies_and_remints(tmp_path, monkeypatch):
    """A competing push lands between our sync and our push; the transaction
    must drop its commit, re-sync, re-apply (re-minting the id), and push —
    leaving NO duplicate id."""
    origin, [repo, other] = _origin_and_clones(tmp_path, n=2)
    real_push = git_ops._push
    calls = {"n": 0}

    def racing_push(repo_root, branch=None):
        calls["n"] += 1
        if calls["n"] == 1:
            # Concurrent writer grabs #1 and pushes first.
            _add_apply(other / "Backlog.md")()
            _git(other, "add", "Backlog.md")
            _git(other, "commit", "-q", "-m", "other add #1")
            _git(other, "push", "-q", "origin", "main")
            return "push-race"
        return real_push(repo_root, branch)

    monkeypatch.setattr(git_ops, "_push", racing_push)

    result, status = transactional_write(
        repo, [repo / "Backlog.md"], _add_apply(repo / "Backlog.md"), "backlog: add_item"
    )
    # We re-minted to #2 after the re-sync (origin already had #1).
    assert result == "added #2", result
    assert "pushed" in status, status
    assert _ids_on_origin(origin, tmp_path) == [1, 2]  # both present, no dup


def test_push_disabled_commits_locally(tmp_path):
    origin, [repo] = _origin_and_clones(tmp_path)
    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()
    result, status = transactional_write(
        repo, [repo / "Backlog.md"], _add_apply(repo / "Backlog.md"), "backlog: add_item", push=False
    )
    assert result == "added #1"
    assert "push disabled" in status, status
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() != head_before  # local commit made
    assert _ids_on_origin(origin, tmp_path) == []  # not pushed


def test_apply_failure_makes_no_commit(tmp_path):
    origin, [repo] = _origin_and_clones(tmp_path)
    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()

    def failing_apply():
        return False, "heading not found"

    result, status = transactional_write(repo, [repo / "Backlog.md"], failing_apply, "backlog: x")
    assert result == "heading not found"
    assert "apply-failed" in status, status
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == head_before


def test_sync_skipped_when_tree_dirty(tmp_path):
    """A concurrent unstaged edit must never be clobbered by the sync reset."""
    origin, [repo] = _origin_and_clones(tmp_path)
    # advance origin so a sync *would* move HEAD
    other = tmp_path / "c2"
    _git(tmp_path, "clone", "-q", str(origin), str(other))
    _config(other)
    (other / "extra.md").write_text("x\n")
    _git(other, "add", "extra.md")
    _git(other, "commit", "-q", "-m", "advance")
    _git(other, "push", "-q", "origin", "main")
    # leave a dirty edit in repo
    (repo / "Backlog.md").write_text(SEED + "\nconcurrent hand-edit\n")
    assert sync_to_origin(repo) is False
    assert "concurrent hand-edit" in (repo / "Backlog.md").read_text()  # preserved


def test_sync_fast_forwards_clean_tree(tmp_path):
    origin, [repo] = _origin_and_clones(tmp_path)
    other = tmp_path / "c2"
    _git(tmp_path, "clone", "-q", str(origin), str(other))
    _config(other)
    (other / "extra.md").write_text("x\n")
    _git(other, "add", "extra.md")
    _git(other, "commit", "-q", "-m", "advance")
    _git(other, "push", "-q", "origin", "main")
    assert sync_to_origin(repo) is True
    assert (repo / "extra.md").exists()  # pulled
