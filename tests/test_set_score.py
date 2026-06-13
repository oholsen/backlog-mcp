"""Tests for the set_score tool — merge-on-update and CSV quoting."""

from __future__ import annotations

import importlib

import pytest

from backlog_mcp.parser import parse_scores_text


@pytest.fixture
def srv(tmp_path, monkeypatch):
    scores = tmp_path / "scores.csv"
    scores.write_text("id,complexity,value,ready,blocked_by,tags,notes\n")
    monkeypatch.setenv("BACKLOG_PATH", str(tmp_path / "Backlog.md"))
    monkeypatch.setenv("BACKLOG_SCORES", str(scores))
    monkeypatch.setenv("BACKLOG_REPO_ROOT", str(tmp_path))
    from backlog_mcp import server as s
    importlib.reload(s)
    return s, scores


def test_insert_then_partial_update_preserves_other_fields(srv):
    """The regression: updating one field must not blank the rest."""
    s, scores = srv
    s.tool_set_score({
        "id": 321, "complexity": 3, "value": 1, "ready": "Y",
        "tags": ["infra"], "notes": "Security Findings dashboard",
    })
    # Update only value + blocked_by, as a caller naturally would.
    s.tool_set_score({"id": 321, "value": 3, "blocked_by": [783]})

    row = parse_scores_text(scores.read_text())[321]
    assert row.value == 3            # updated
    assert row.blocked_by == [783]   # updated
    assert row.complexity == 3       # preserved
    assert row.ready == "Y"          # preserved
    assert row.tags == ["infra"]     # preserved
    assert row.notes == "Security Findings dashboard"  # preserved


def test_insert_new_row(srv):
    s, scores = srv
    assert "inserted" in s.tool_set_score({"id": 783, "complexity": 2, "value": 4, "ready": "Y"})
    row = parse_scores_text(scores.read_text())[783]
    assert (row.complexity, row.value, row.ready) == (2, 4, "Y")


def test_update_reports_updated(srv):
    s, _ = srv
    s.tool_set_score({"id": 5, "value": 2})
    assert "updated" in s.tool_set_score({"id": 5, "value": 3})


def test_notes_with_comma_round_trips(srv):
    """Unquoted commas in notes used to shift columns and corrupt the row."""
    s, scores = srv
    note = "unblocker for #321; see /api/findings, handle_findings, ~line 45"
    s.tool_set_score({"id": 783, "value": 4, "notes": note})
    row = parse_scores_text(scores.read_text())[783]
    assert row.notes == note
    assert row.value == 4


def test_multi_blocked_by_round_trips(srv):
    """blocked_by uses commas internally — it must be quoted in the CSV."""
    s, scores = srv
    s.tool_set_score({"id": 100, "value": 2, "blocked_by": [783, 784]})
    row = parse_scores_text(scores.read_text())[100]
    assert row.blocked_by == [783, 784]
    assert row.value == 2


def test_explicit_empty_clears_field(srv):
    s, scores = srv
    s.tool_set_score({"id": 9, "value": 3, "blocked_by": [1, 2], "notes": "x"})
    s.tool_set_score({"id": 9, "blocked_by": [], "notes": ""})
    row = parse_scores_text(scores.read_text())[9]
    assert row.blocked_by == []
    assert row.notes == ""
    assert row.value == 3  # untouched
