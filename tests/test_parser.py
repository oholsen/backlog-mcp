from pathlib import Path

from backlog_mcp.parser import (
    index_by_id,
    one_line_summary,
    parse_backlog,
    parse_scores_text,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_backlog_counts_and_status():
    items = parse_backlog(FIXTURES / "small-backlog.md")
    by_id = index_by_id(items)

    assert len(items) == 5
    assert {it.id for it in items} == {1, 2, 3, 5, 10}

    assert by_id[1].section == "Section A"
    assert by_id[1].subsection is None
    assert by_id[1].in_progress is False
    assert by_id[1].archived is False

    assert by_id[2].in_progress is True
    assert by_id[2].archived is False

    assert by_id[3].subsection == "Subsection X"
    assert by_id[3].section == "Section A"

    assert by_id[5].archived is True
    assert by_id[5].in_progress is False  # archived overrides in_progress


def test_parse_backlog_files_and_severity_unstrike():
    items = parse_backlog(FIXTURES / "small-backlog.md")
    by_id = index_by_id(items)
    # Strikethrough markers stripped from files / severity
    assert by_id[5].files == "src/e.rs"
    assert by_id[5].severity == "Low"


def test_parse_scores_handles_comments_and_lists():
    csv_text = """\
# leading comment, ignored
id,complexity,value,ready,blocked_by,tags,notes
1,2,3,Y,,foo;bar,first
2,,4,N,1,baz,blocked-by-1
"""
    scores = parse_scores_text(csv_text)
    assert set(scores) == {1, 2}
    assert scores[1].complexity == 2
    assert scores[1].tags == ["foo", "bar"]
    assert scores[2].complexity is None
    assert scores[2].blocked_by == [1]


def test_one_line_summary_strips_status_prefix():
    assert one_line_summary("**IN PROGRESS (foo)** **Real title.** Body.") == "Real title"
    assert one_line_summary("**DONE (PR #1).** Archived stuff. More.") == "Archived stuff"
    assert one_line_summary("Plain prose without bold marker.") == "Plain prose without bold marker"


def test_one_line_summary_truncates():
    long = "**" + ("x" * 200) + "**"
    s = one_line_summary(long, max_chars=50)
    assert len(s) == 50
    assert s.endswith("…")
