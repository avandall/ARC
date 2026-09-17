"""ARC Main CLI Entrypoint."""

import typer

from arc.cli.commands.catalog import catalog_app
from arc.cli.commands.debug import debug_command
from arc.cli.commands.gate import gate_command
from arc.cli.commands.incidents import incidents_app
from arc.cli.commands.repro import repro_command

app = typer.Typer(
    name="arc",
    help="ARC CLI - Autonomous Reliability & Chaos Engine",
    add_completion=False,
)

app.command("repro")(repro_command)
app.command("debug")(debug_command)
app.command("gate")(gate_command)
app.add_typer(catalog_app, name="catalog")
app.add_typer(incidents_app, name="incidents")


if __name__ == "__main__":
    app()
