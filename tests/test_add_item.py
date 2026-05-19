"""Tests for the add_item tool — focused on the Inbox default behaviour.

The MCP server module reads BACKLOG_PATH at import time so we use a
fixture-as-target pattern: copy the fixture to a tmp_path, set env vars,
import (or re-import) the module, exercise.
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

    # Re-import server.py with new env vars so module-level paths re-bind
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
    archive_idx = text.find("## Done — archive")
    new_row_idx = text.find("Test item filed without section")

    assert inbox_idx < new_row_idx < archive_idx, "new row should land between Inbox and Done — archive"


def test_add_item_explicit_section(server_with_inbox):
    srv, backlog = server_with_inbox
    result = srv.tool_add_item({
        "section": "Section A",
        "files": "src/y.rs",
        "description": "Test item explicitly placed.",
    })
    assert "Added" in result

    text = backlog.read_text()
    section_a_idx = text.find("## Section A")
    inbox_idx = text.find("## Inbox")
    new_row_idx = text.find("Test item explicitly placed")
    assert section_a_idx < new_row_idx < inbox_idx


def test_add_item_heading_format_with_body(server_with_inbox):
    srv, backlog = server_with_inbox
    result = srv.tool_add_item({
        "description": "Heading-format item",
        "body": "First paragraph.\n\nSecond paragraph.",
    })
    assert "Added" in result, result
    text = backlog.read_text()
    assert "### #6 Heading-format item" in text
    assert "First paragraph." in text
    assert "Second paragraph." in text

    # Round-trip: parser sees the body.
    from backlog_mcp.parser import index_by_id, parse_backlog_text
    by_id = index_by_id(parse_backlog_text(text))
    assert by_id[6].description == "Heading-format item"
    assert by_id[6].body == "First paragraph.\n\nSecond paragraph."


def test_add_item_requires_files_for_table_format(server_with_inbox):
    srv, _ = server_with_inbox
    result = srv.tool_add_item({"description": "no files, no body"})
    assert "files is required" in result


def test_add_item_assigns_next_free_id(server_with_inbox):
    srv, backlog = server_with_inbox
    # Fixture max ID is 5 (the archived one). Next free should be 6.
    result = srv.tool_add_item({
        "files": "f",
        "description": "first new",
    })
    assert "#6" in result, result
    result = srv.tool_add_item({
        "files": "f",
        "description": "second new",
    })
    assert "#7" in result, result
