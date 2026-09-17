"""ARC Main CLI Entrypoint."""

import typer

from cli.commands.catalog import catalog_app
from cli.commands.debug import debug_command
from cli.commands.gate import gate_command
from cli.commands.repro import repro_command

app = typer.Typer(
    name="arc",
    help="ARC CLI - Autonomous Reliability & Chaos Engine",
    add_completion=False,
)

app.command("repro")(repro_command)
app.command("debug")(debug_command)
app.command("gate")(gate_command)
app.add_typer(catalog_app, name="catalog")


if __name__ == "__main__":
    app()
