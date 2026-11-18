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
