from pathlib import Path

from backlog_mcp.parser import (
    index_by_id,
    one_line_summary,
    parse_backlog,
    parse_backlog_text,
    parse_scores_text,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_backlog_counts_and_status():
    items = parse_backlog(FIXTURES / "small-backlog.md")
    by_id = index_by_id(items)

    assert len(items) == 4
    assert {it.id for it in items} == {1, 2, 3, 10}

    assert by_id[1].section == "Section A"
    assert by_id[1].subsection is None
    assert by_id[1].in_progress is False
    assert by_id[1].archived is False

    assert by_id[2].in_progress is True
    assert by_id[2].archived is False

    assert by_id[3].subsection == "Subsection X"
    assert by_id[3].section == "Section A"


def test_parse_backlog_files():
    items = parse_backlog(FIXTURES / "small-backlog.md")
    by_id = index_by_id(items)
    assert by_id[1].files == "src/backlog_mcp/server.py"
    assert by_id[2].files == "src/backlog_mcp/server.py"


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
    assert one_line_summary("[in-progress: feat-foo] **Real title.** Body.") == "Real title"
    assert one_line_summary("[done: PR #1, 2026-05-01] Archived stuff. More.") == "Archived stuff"
    assert one_line_summary("[open] Plain prose.") == "Plain prose"
    assert one_line_summary("Plain prose without status tag.") == "Plain prose without status tag"


def test_parse_heading_format_items():
    text = """\
## Inbox

### #42 [open] Inbox heading-format item

| # | Status | File | Description |
|---|--------|------|-------------|
| 7 | [open] | x | Table row. |
"""
    items = parse_backlog_text(text)
    by_id = index_by_id(items)

    assert {it.id for it in items} == {7, 42}

    assert by_id[42].section == "Inbox"
    assert by_id[42].archived is False
    assert by_id[42].in_progress is False
    assert by_id[42].description == "Inbox heading-format item"
    assert by_id[42].files == ""

    assert by_id[7].description == "Table row."


def test_heading_item_in_progress():
    text = """\
## Section A

### #10 [in-progress: feat-10] Active item
### #11 [done: PR #99, 2026-05-01] Done item
"""
    items = parse_backlog_text(text)
    by_id = index_by_id(items)
    assert by_id[10].in_progress is True
    assert by_id[10].archived is False
    assert by_id[10].description == "Active item"
    assert by_id[11].archived is True
    assert by_id[11].in_progress is False
    assert by_id[11].description == "Done item"


def test_heading_item_body_captured():
    text = """\
## Inbox

### #42 [open] Heading-format item

First paragraph of the body.

Second paragraph with a list:

- one
- two

### #43 [open] Next item

Body of 43.

## Other

### #44 [open] In another section

Final body.
"""
    items = parse_backlog_text(text)
    by_id = index_by_id(items)
    assert by_id[42].body.startswith("First paragraph of the body.")
    assert "- two" in by_id[42].body
    assert by_id[43].body == "Body of 43."
    assert by_id[44].body == "Final body."


def test_heading_item_body_terminated_by_table_row():
    text = """\
## Inbox

### #42 [open] Heading with body

Body paragraph.

| # | Status | File | Description |
|---|--------|------|-------------|
| 7 | [open] | x | Row stops body collection. |
"""
    items = parse_backlog_text(text)
    by_id = index_by_id(items)
    assert by_id[42].body == "Body paragraph."
    assert by_id[7].description == "Row stops body collection."


def test_heading_item_body_empty_when_none():
    text = """\
## Inbox

### #42 [open] Just a title
### #43 [open] Next title
"""
    items = parse_backlog_text(text)
    by_id = index_by_id(items)
    assert by_id[42].body == ""
    assert by_id[43].body == ""


def test_heading_item_does_not_become_subsection():
    text = """\
## Inbox

### #42 [open] Heading item

| # | Status | File | Description |
|---|--------|------|-------------|
| 7 | [open] | x | Row after the heading item. |
"""
    items = parse_backlog_text(text)
    by_id = index_by_id(items)
    assert by_id[7].subsection is None
    assert by_id[7].section == "Inbox"


def test_one_line_summary_truncates():
    long = "**" + ("x" * 200) + "**"
    s = one_line_summary(long, max_chars=50)
    assert len(s) == 50
    assert s.endswith("…")
