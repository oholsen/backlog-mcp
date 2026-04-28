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
