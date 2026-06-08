from pathlib import Path

from backlog_mcp.lint import lint_file

FIXTURES = Path(__file__).parent / "fixtures"


def test_clean_backlog_passes(tmp_path):
    target = tmp_path / "Backlog.md"
    target.write_text((FIXTURES / "small-backlog.md").read_text())
    result = lint_file(target, repo_root=tmp_path, skip_branch_check=True)
    assert result.ok
    assert result.errors == []


def test_duplicate_ids_fails(tmp_path):
    target = tmp_path / "Backlog.md"
    target.write_text((FIXTURES / "duplicate-ids.md").read_text())
    result = lint_file(target, repo_root=tmp_path, skip_branch_check=True)
    assert not result.ok
    assert any("duplicate ID #1" in e for e in result.errors)


def test_conflict_marker_fails(tmp_path):
    target = tmp_path / "Backlog.md"
    target.write_text(
        "# Backlog\n\n## Section A\n\n"
        "| # | File | Severity | Description |\n"
        "|---|---|---|---|\n"
        "| 1 | x | Low | First. |\n"
        "<<<<<<< HEAD\n"
        "| 2 | y | Low | Second. |\n"
        "=======\n"
        "| 2 | z | High | Conflict. |\n"
        ">>>>>>> branch\n"
    )
    result = lint_file(target, repo_root=tmp_path, skip_branch_check=True)
    assert not result.ok
    assert any("conflict marker" in e for e in result.errors)


def test_missing_file_fails(tmp_path):
    result = lint_file(tmp_path / "nonexistent.md", skip_branch_check=True)
    assert not result.ok
    assert any("not readable" in e for e in result.errors)


def test_blank_line_in_table_warns(tmp_path):
    target = tmp_path / "Backlog.md"
    target.write_text(
        "## Inbox\n\n"
        "| # | Status | File | Description |\n"
        "|---|--------|------|-------------|\n"
        "| 1 | [open] | x | First. |\n"
        "\n"
        "| 2 | [open] | y | Second. |\n"
    )
    result = lint_file(target, repo_root=tmp_path, skip_branch_check=True)
    assert any("blank line inside table" in w for w in result.warnings), result.warnings


def test_heading_flush_against_row_warns(tmp_path):
    target = tmp_path / "Backlog.md"
    target.write_text(
        "## Inbox\n\n"
        "| # | Status | File | Description |\n"
        "|---|--------|------|-------------|\n"
        "| 1 | [open] | x | Row. |\n"
        "## Next Section\n"
    )
    result = lint_file(target, repo_root=tmp_path, skip_branch_check=True)
    assert any("flush against prior table row" in w for w in result.warnings), result.warnings


def test_missing_table_header_warns(tmp_path):
    target = tmp_path / "Backlog.md"
    target.write_text(
        "## Inbox\n\n"
        "Some prose.\n\n"
        "| 1 | [open] | x | Row without header. |\n"
    )
    result = lint_file(target, repo_root=tmp_path, skip_branch_check=True)
    assert any("missing header" in w for w in result.warnings), result.warnings


def test_fix_repairs_blank_in_table_and_heading_flush(tmp_path):
    target = tmp_path / "Backlog.md"
    target.write_text(
        "## Inbox\n\n"
        "| # | Status | File | Description |\n"
        "|---|--------|------|-------------|\n"
        "| 1 | [open] | x | First. |\n"
        "\n"
        "| 2 | [open] | y | Second. |\n"
        "## Next Section\n"
        "\n"
        "| # | Status | File | Description |\n"
        "|---|--------|------|-------------|\n"
        "| 3 | [open] | z | Third. |\n"
    )
    result = lint_file(target, repo_root=tmp_path, skip_branch_check=True, fix=True)
    assert result.fixed == 2, (result.fixed, result.summary())
    fixed_text = target.read_text()
    # No blank line between the two rows of the first table
    assert "| 1 | [open] | x | First. |\n| 2 | [open] | y | Second. |\n" in fixed_text
    # Blank line inserted before the heading
    assert "| 2 | [open] | y | Second. |\n\n## Next Section\n" in fixed_text
    # Re-lint clean for these two checks
    result2 = lint_file(target, repo_root=tmp_path, skip_branch_check=True)
    assert not any("blank line inside table" in w for w in result2.warnings)
    assert not any("flush against prior table row" in w for w in result2.warnings)


def test_fix_no_op_on_clean_file(tmp_path):
    target = tmp_path / "Backlog.md"
    target.write_text((FIXTURES / "small-backlog.md").read_text())
    before = target.read_text()
    result = lint_file(target, repo_root=tmp_path, skip_branch_check=True, fix=True)
    assert result.fixed == 0
    assert target.read_text() == before
