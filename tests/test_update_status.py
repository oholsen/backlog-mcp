"""Tests for tool_update_status — bracket-style status format."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def server_with_inbox(tmp_path, monkeypatch):
    backlog = tmp_path / "Backlog.md"
    backlog.write_text((FIXTURES / "with-inbox.md").read_text())
    monkeypatch.setenv("BACKLOG_PATH", str(backlog))
    monkeypatch.setenv("BACKLOG_SCORES", str(tmp_path / "scores.csv"))
    monkeypatch.setenv("BACKLOG_REPO_ROOT", str(tmp_path))
    from backlog_mcp import server as srv
    importlib.reload(srv)
    return srv, backlog


def test_done_deletes_row(server_with_inbox):
    srv, backlog = server_with_inbox
    result = srv.tool_update_status({"id": 1, "status": "done"})
    assert "done" in result, result

    text = backlog.read_text()
    # Item #1 should be gone
    assert "| 1 |" not in text
    assert "~~1~~" not in text


def test_done_appends_to_changelog(tmp_path, monkeypatch):
    backlog = tmp_path / "Backlog.md"
    backlog.write_text(
        "# Backlog\n\n## Section A\n\n"
        "| # | Status | File | Description |\n"
        "|---|--------|------|-------------|\n"
        "| 1 | [open] | src/x.py | Open item. |\n"
    )
    inbox = tmp_path / "CHANGELOG-INBOX.md"
    inbox.write_text("# Inbox\n\n<!-- append new DONE lines below this line -->\n")
    monkeypatch.setenv("BACKLOG_PATH", str(backlog))
    monkeypatch.setenv("BACKLOG_SCORES", str(tmp_path / "scores.csv"))
    monkeypatch.setenv("BACKLOG_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("CHANGELOG_INBOX_PATH", str(inbox))
    from backlog_mcp import server as srv
    importlib.reload(srv)

    result = srv.tool_update_status({
        "id": 1, "status": "done", "summary": "fixed the thing",
        "pr": "42", "changelog": True,
    })
    assert "done" in result, result
    assert "CHANGELOG-INBOX" in result, result
    assert "fixed the thing" in inbox.read_text()


def test_in_progress_updates_status_column(server_with_inbox):
    srv, backlog = server_with_inbox
    result = srv.tool_update_status({
        "id": 1, "status": "in_progress", "branch": "feat-1",
    })
    assert "in_progress" in result, result

    text = backlog.read_text()
    assert "| 1 | [in-progress: feat-1] |" in text
    # Item #1 still present, not deleted
    assert "| 1 |" in text


def test_open_resets_to_open_tag(server_with_inbox):
    srv, backlog = server_with_inbox
    # First mark in-progress, then back to open
    srv.tool_update_status({"id": 1, "status": "in_progress", "branch": "feat-1"})
    result = srv.tool_update_status({"id": 1, "status": "open"})
    assert "open" in result, result

    text = backlog.read_text()
    assert "| 1 | [open] |" in text


def test_in_progress_requires_branch(server_with_inbox):
    srv, _ = server_with_inbox
    result = srv.tool_update_status({"id": 1, "status": "in_progress"})
    assert "branch is required" in result


def test_unknown_id_returns_error(server_with_inbox):
    srv, _ = server_with_inbox
    result = srv.tool_update_status({"id": 9999, "status": "done"})
    assert "not found" in result


def test_done_heading_item_deletes_block_preserves_next_section(tmp_path, monkeypatch):
    backlog = tmp_path / "Backlog.md"
    backlog.write_text(
        "# Backlog\n\n## Section A\n\n"
        "### #1 [open] Rich item\n\n"
        "Body text.\n\n"
        "## Inbox\n\n"
        "| # | Status | File | Description |\n"
        "|---|--------|------|-------------|\n"
        "| 2 | [open] | src/x.py | Inbox item. |\n"
    )
    monkeypatch.setenv("BACKLOG_PATH", str(backlog))
    monkeypatch.setenv("BACKLOG_SCORES", str(tmp_path / "scores.csv"))
    monkeypatch.setenv("BACKLOG_REPO_ROOT", str(tmp_path))
    from backlog_mcp import server as srv
    importlib.reload(srv)

    result = srv.tool_update_status({"id": 1, "status": "done"})
    assert "done" in result, result

    text = backlog.read_text()
    assert "### #1" not in text
    assert "Body text." not in text
    # Next section heading must be present with a blank-line separator
    assert "\n\n## Inbox\n" in text
    assert "| 2 |" in text
