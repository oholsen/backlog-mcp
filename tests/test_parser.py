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


def test_parse_backlog_files_unstrike():
    items = parse_backlog(FIXTURES / "small-backlog.md")
    by_id = index_by_id(items)
    # Strikethrough markers stripped from files
    assert by_id[5].files == "src/e.rs"


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


def test_parse_heading_format_items():
    """`### #NNN <desc>` headings are parsed as Items so they collide with
    table-row ids for next_id selection and lint duplicate checks."""
    text = """\
## Inbox

### #42 Inbox heading-format item

| # | File | Description |
| - | ---- | ----------- |
| 7 | x | Table row. |

## Done — archive

### #945 KC300 beacon retired
### #946 Another archived heading
"""
    items = parse_backlog_text(text)
    by_id = index_by_id(items)

    assert {it.id for it in items} == {7, 42, 945, 946}

    assert by_id[42].section == "Inbox"
    assert by_id[42].archived is False
    assert by_id[42].description == "Inbox heading-format item"
    assert by_id[42].files == ""

    assert by_id[945].archived is True
    assert by_id[946].archived is True


def test_heading_item_body_captured():
    """Lines between `### #NNN <title>` and the next boundary become `body`."""
    text = """\
## Inbox

### #42 Heading-format item

First paragraph of the body.

Second paragraph with a list:

- one
- two

### #43 Next item

Body of 43.

## Other

### #44 In another section

Final body.
"""
    items = parse_backlog_text(text)
    by_id = index_by_id(items)
    assert by_id[42].body.startswith("First paragraph of the body.")
    assert "- two" in by_id[42].body
    assert by_id[43].body == "Body of 43."
    assert by_id[44].body == "Final body."


def test_heading_item_body_terminated_by_table_row():
    """A table row after a heading item ends body collection."""
    text = """\
## Inbox

### #42 Heading with body

Body paragraph.

| 7 | x | Row stops body collection. |
"""
    items = parse_backlog_text(text)
    by_id = index_by_id(items)
    assert by_id[42].body == "Body paragraph."
    assert by_id[7].description == "Row stops body collection."


def test_heading_item_body_empty_when_none():
    """A heading item with no body has `body == ''`."""
    text = """\
## Inbox

### #42 Just a title
### #43 Next title
"""
    items = parse_backlog_text(text)
    by_id = index_by_id(items)
    assert by_id[42].body == ""
    assert by_id[43].body == ""


def test_heading_item_does_not_become_subsection():
    """An `### #NNN ...` heading is consumed as an Item, so a following table
    row stays under the parent section with no subsection."""
    text = """\
## Inbox

### #42 Heading item

| 7 | x | Row after the heading item. |
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
