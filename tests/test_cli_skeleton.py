# tests/test_cli_skeleton.py
from click.testing import CliRunner

from mr_review.cli import main


def test_help_lists_the_three_commands():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    for cmd in ("sync", "status", "publish"):
        assert cmd in result.output


def test_subcommand_accepts_optional_mr_and_repo():
    # sync with an mr ref and repo override parses without error at the CLI layer
    result = CliRunner().invoke(main, ["sync", "123", "-R", "grp/repo"])
    # stub raises NotImplementedError -> click reports non-zero but parsed args first
    assert "no such option" not in result.output.lower()
