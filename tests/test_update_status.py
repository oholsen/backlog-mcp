"""Tests for tool_update_status — focused on the move-to-archive behaviour.

Mirrors the fixture-as-target pattern from test_add_item.py: copy the fixture
into tmp_path, set env vars, reload the server module so module-level paths
re-bind.
"""

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


def test_done_moves_row_to_archive(server_with_inbox):
    srv, backlog = server_with_inbox
    result = srv.tool_update_status({"id": 1, "status": "done"})
    assert "done" in result and "moved to archive" in result, result

    text = backlog.read_text()
    archive_idx = text.find("## Done — archive")
    row1_idx = text.find("| ~~1~~")
    assert archive_idx < row1_idx, "row #1 should now sit below the archive heading"

    # The original Section A no longer holds a #1 row.
    section_a_idx = text.find("## Section A")
    section_b_or_next = text.find("\n## ", section_a_idx + 1)
    section_a_region = text[section_a_idx:section_b_or_next]
    assert "| 1 |" not in section_a_region
    assert "| ~~1~~" not in section_a_region


def test_done_idempotent_when_already_in_archive(server_with_inbox):
    srv, backlog = server_with_inbox
    # #5 is pre-archived in the fixture. Re-marking done must not duplicate.
    before = backlog.read_text()
    result = srv.tool_update_status({"id": 5, "status": "done"})
    assert "done" in result, result
    assert "moved to archive" not in result, result
    text = backlog.read_text()
    assert text.count("| ~~5~~") == 1
    # File content should be unchanged (idempotent on a fully-archived row).
    assert text == before


def test_done_with_summary_adds_marker_and_relocates(server_with_inbox):
    srv, backlog = server_with_inbox
    result = srv.tool_update_status({
        "id": 2, "status": "done", "summary": "race fix",
    })
    assert "done" in result and "moved to archive" in result, result

    text = backlog.read_text()
    assert "**DONE (race fix)**" in text
    archive_idx = text.find("## Done — archive")
    row2_idx = text.find("| ~~2~~")
    assert archive_idx < row2_idx


def test_done_falls_back_to_in_place_when_no_archive(tmp_path, monkeypatch):
    backlog = tmp_path / "Backlog.md"
    backlog.write_text(
        "# Backlog\n\n"
        "## Section A\n\n"
        "| # | File | Description |\n"
        "|---|---|---|\n"
        "| 1 | src/x.py | Open item. |\n"
    )
    monkeypatch.setenv("BACKLOG_PATH", str(backlog))
    monkeypatch.setenv("BACKLOG_SCORES", str(tmp_path / "scores.csv"))
    monkeypatch.setenv("BACKLOG_REPO_ROOT", str(tmp_path))
    from backlog_mcp import server as srv
    importlib.reload(srv)

    result = srv.tool_update_status({"id": 1, "status": "done"})
    assert "done" in result, result
    assert "moved to archive" not in result, result
    text = backlog.read_text()
    assert "| ~~1~~" in text


def test_done_inserts_above_archive_subsection(tmp_path, monkeypatch):
    """If `## Done — archive` has a `### Subsection` beneath it (e.g. the
    sensor backlog's `### Inbox` under archive), relocated rows land in the
    archive's primary table, above the subsection — they don't fall into it.
    """
    backlog = tmp_path / "Backlog.md"
    backlog.write_text(
        "# Backlog\n\n"
        "## Section A\n\n"
        "| # | File | Description |\n"
        "|---|---|---|\n"
        "| 1 | src/x.py | Open item. |\n\n"
        "## Done — archive\n\n"
        "| # | File | Description |\n"
        "|---|---|---|\n"
        "| ~~9~~ | ~~src/y.py~~ | **DONE.** Earlier. |\n\n"
        "### Inbox\n\n"
        "| # | File | Description |\n"
        "|---|---|---|\n"
        "| 7 | src/z.py | Parked. |\n"
    )
    monkeypatch.setenv("BACKLOG_PATH", str(backlog))
    monkeypatch.setenv("BACKLOG_SCORES", str(tmp_path / "scores.csv"))
    monkeypatch.setenv("BACKLOG_REPO_ROOT", str(tmp_path))
    from backlog_mcp import server as srv
    importlib.reload(srv)

    result = srv.tool_update_status({"id": 1, "status": "done"})
    assert "moved to archive" in result, result

    text = backlog.read_text()
    archive_idx = text.find("## Done — archive")
    subsection_idx = text.find("### Inbox")
    row1_idx = text.find("| ~~1~~")
    assert archive_idx < row1_idx < subsection_idx, text


def test_in_progress_does_not_relocate(server_with_inbox):
    srv, backlog = server_with_inbox
    result = srv.tool_update_status({
        "id": 1, "status": "in_progress", "branch": "feat-1",
    })
    assert "in_progress" in result, result
    assert "moved to archive" not in result
    text = backlog.read_text()
    # Still under Section A, marked in progress.
    section_a_idx = text.find("## Section A")
    inbox_idx = text.find("## Inbox")
    in_progress_idx = text.find("**IN PROGRESS (feat-1)**")
    assert section_a_idx < in_progress_idx < inbox_idx
