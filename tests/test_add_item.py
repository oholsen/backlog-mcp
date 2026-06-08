"""Tests for the add_item tool (heading-only) and the durable next-id marker."""

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


def test_add_item_defaults_to_inbox(server_with_inbox):
    srv, backlog = server_with_inbox
    result = srv.tool_add_item({
        "files": "src/x.rs",
        "description": "Test item filed without section.",
    })
    assert "Added" in result, result

    text = backlog.read_text()
    inbox_idx = text.find("## Inbox")
    new_idx = text.find("### #3 [open] Test item filed without section.")
    assert inbox_idx < new_idx, "new heading should land inside the Inbox section"
    # files render as a leading _Files: …_ line
    assert "_Files: src/x.rs_" in text


def test_add_item_explicit_section(server_with_inbox):
    srv, backlog = server_with_inbox
    result = srv.tool_add_item({
        "section": "Section A",
        "description": "Test item explicitly placed.",
    })
    assert "Added" in result

    text = backlog.read_text()
    section_a_idx = text.find("## Section A")
    inbox_idx = text.find("## Inbox")
    new_idx = text.find("### #3 [open] Test item explicitly placed.")
    assert section_a_idx < new_idx < inbox_idx


def test_add_item_heading_format_with_body(server_with_inbox):
    srv, backlog = server_with_inbox
    result = srv.tool_add_item({
        "description": "Heading-format item",
        "body": "First paragraph.\n\nSecond paragraph.",
    })
    assert "Added" in result, result
    text = backlog.read_text()
    assert "### #3 [open] Heading-format item" in text
    assert "First paragraph." in text
    assert "Second paragraph." in text

    from backlog_mcp.parser import index_by_id, parse_backlog_text
    by_id = index_by_id(parse_backlog_text(text))
    assert by_id[3].description == "Heading-format item"
    assert by_id[3].body == "First paragraph.\n\nSecond paragraph."


def test_add_item_title_only_ok(server_with_inbox):
    """files and body are both optional — a bare title is a valid item."""
    srv, backlog = server_with_inbox
    result = srv.tool_add_item({"description": "Bare title item"})
    assert "Added" in result, result
    assert "### #3 [open] Bare title item" in backlog.read_text()


def test_add_item_assigns_next_free_id(server_with_inbox):
    srv, _ = server_with_inbox
    # Fixture max ID is 2. Next free should be 3, then 4.
    assert "#3" in srv.tool_add_item({"description": "first new"})
    assert "#4" in srv.tool_add_item({"description": "second new"})


def test_add_item_writes_next_id_marker(server_with_inbox):
    srv, backlog = server_with_inbox
    srv.tool_add_item({"description": "first new"})  # -> #3
    text = backlog.read_text()
    assert "<!-- next-id: 4 -->" in text, text


def test_marker_prevents_id_reuse_after_delete(server_with_inbox):
    """The durable marker must stop a deleted (DONE) ID from being re-issued."""
    srv, backlog = server_with_inbox
    srv.tool_add_item({"description": "soon to be done"})  # -> #3, marker -> 4
    # Mark #3 done — heading-format items are deleted from the file.
    srv.tool_update_status({"id": 3, "status": "done"})
    text = backlog.read_text()
    assert "### #3 " not in text, "DONE item should be deleted"
    # live max is back to 2, but the marker holds the high-water mark at 4.
    assert srv._next_free_id_from_text(text) == 4
    assert "#4" in srv.tool_add_item({"description": "next after delete"})
