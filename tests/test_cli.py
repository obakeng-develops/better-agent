from typer.testing import CliRunner

from better_agent.cli import app

runner = CliRunner()


def test_short_help_works_on_app_and_subcommands():
    assert runner.invoke(app, ["-h"]).exit_code == 0
    assert runner.invoke(app, ["list", "-h"]).exit_code == 0


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.startswith("bta ")


def test_n_is_not_bound_to_limit_or_note():
    # clig.dev reserves -n for --dry-run
    for cmd in (["list"], ["search", "x"], ["link", "a", "b"]):
        result = runner.invoke(app, [*cmd, "-n", "5"])
        assert result.exit_code == 2, cmd
