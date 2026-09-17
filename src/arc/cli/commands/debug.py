"""ARC CLI `arc debug` command implementation."""

import sys
import time
from pathlib import Path

import typer
from rich.console import Console

from arc.cli.proxy.debugger_proxy import LocalDebuggerProxy

console = Console()


def debug_command(
    repro: str | None = typer.Option(
        None, "--repro", "-r", help="Path to reproducer YAML spec file"
    ),
    port: int = typer.Option(8089, "--port", "-p", help="Proxy port to bind"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Proxy host to bind"),
    block: bool = typer.Option(
        False, "--block", help="Keep proxy running in foreground loop until Ctrl+C"
    ),
) -> None:
    """Start local replay debugger proxy and print environment setup instructions."""
    if repro:
        repro_path = Path(repro)
        if not repro_path.exists():
            console.print(f"[bold yellow]Warning: Reproducer file '{repro}' not found[/bold yellow]")

    proxy = LocalDebuggerProxy(repro_file=repro, requested_port=port, host=host)
    bound_port, fallback_occurred = proxy.start()

    if fallback_occurred:
        console.print(
            f"[bold yellow]Port {port} is occupied. Automatically falling back to port {bound_port}[/bold yellow]"
        )

    env_vars = proxy.get_env_vars()
    console.print(f"[bold green]Local Debugger Proxy started on http://{host}:{bound_port}[/bold green]")
    console.print("\nRun the following commands in your terminal or debugger configuration:")
    console.print(f"export HTTP_PROXY={env_vars['HTTP_PROXY']}")
    console.print(f"export LLM_API_BASE={env_vars['LLM_API_BASE']}\n")

    if block and sys.stdin.isatty():
        console.print("Press Ctrl+C to stop local debugger proxy...")
        try:
            while proxy.is_running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            console.print("\n[bold yellow]Stopping proxy and releasing resources...[/bold yellow]")
        finally:
            proxy.stop()
            console.print("[bold green]Proxy stopped successfully.[/bold green]")
    else:
        # For non-blocking / test invocations, keep proxy active or return clean
        pass
