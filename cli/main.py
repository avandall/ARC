"""ARC Main CLI Entrypoint."""

import typer

from cli.commands.debug import debug_command
from cli.commands.repro import repro_command

app = typer.Typer(
    name="arc",
    help="ARC CLI - Autonomous Reliability & Chaos Engine",
    add_completion=False,
)

app.command("repro")(repro_command)
app.command("debug")(debug_command)


if __name__ == "__main__":
    app()
