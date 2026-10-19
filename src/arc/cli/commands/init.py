"""ARC Interactive Setup Wizard and Configuration Command (TASK-CLI-002).

Guides new users through initial configuration and provides configuration editing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import questionary
import typer
from rich.console import Console
from rich.panel import Panel

from arc.cli.config import ARCConfig
from arc.cli.scaffold import init_arc_scaffold, is_arc_scaffold_initialized

console = Console()

init_app = typer.Typer(
    name="init",
    help="Initialize or configure ARC for the current project",
    add_completion=False,
)


def _trigger_quick_auto_mine(project_root: Path) -> int:
    """Performs an initial fast scan of project code and schemas to extract invariant candidates."""
    catalog_dir = project_root / ".arc" / "catalog"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    mined_file = catalog_dir / "mined_invariants.json"

    candidates: list[dict[str, Any]] = []

    try:
        from arc.control_plane.miner.ast_miner import ASTMiner
        from arc.control_plane.warehouse.db_store import DatabaseStore

        db_store = DatabaseStore.get_shared_instance()
        miner = ASTMiner(db_store=db_store)

        # Scan python files under src/ or current root (excluding .venv, .arc)
        py_files = [
            p
            for p in project_root.rglob("*.py")
            if not any(part.startswith((".", "venv")) for part in p.parts)
        ]
        for py_file in py_files[:30]:
            try:
                code_text = py_file.read_text(encoding="utf-8", errors="ignore")
                extracted = miner.mine_python_source(code_text, filename=str(py_file))
                for item in extracted:
                    cand_dict = item.to_dict()
                    cand_dict["status"] = "pending"
                    candidates.append(cand_dict)
                    try:
                        db_store.insert_candidate(cand_dict)
                    except Exception:
                        pass
            except (OSError, SyntaxError, ValueError) as exc:
                console.print(f"[dim]Skipping file {py_file}: {exc}[/dim]")
    except (ImportError, OSError) as exc:
        console.print(f"[dim]Could not initialize AST miner: {exc}[/dim]")

    mined_file.write_text(json.dumps(candidates, indent=2), encoding="utf-8")
    return len(candidates)


def run_init_wizard(project_root: Path | None = None) -> ARCConfig:
    """Runs the 30-second initial setup wizard using Questionary.

    Asks:
    1. Target Agent / Backend HTTP endpoint URL
    2. Proxy Port (default 8089)
    3. Active LLM Provider
    4. Model Name
    5. API Key (optional)
    6. Prompts to auto-mine invariants: `? Do you want to auto-mine invariants now? [Y/n]`

    Returns:
        The newly created ARCConfig instance.
    """
    root = Path(project_root).resolve() if project_root else Path.cwd().resolve()

    console.print(
        Panel.fit(
            f"[bold cyan]ARC Initial Setup Wizard[/bold cyan]\n"
            f"Configuring project at [bold]{root}[/bold]",
            border_style="cyan",
        )
    )

    # 1. Target URL
    target_url = questionary.text(
        "Target Agent / Backend URL:",
        default="http://localhost:8000",
    ).ask()
    if not target_url:
        target_url = "http://localhost:8000"

    # 2. Proxy Port
    proxy_port_str = questionary.text(
        "ARC Debugger Proxy Port:",
        default="8089",
    ).ask()
    proxy_port = int(proxy_port_str) if proxy_port_str and proxy_port_str.isdigit() else 8089

    # 3. Active Provider
    provider = questionary.select(
        "Active LLM Provider:",
        choices=["openai", "anthropic", "gemini", "ollama"],
        default="openai",
    ).ask()
    if not provider:
        provider = "openai"

    # 4. Model Name
    default_models = {
        "openai": "gpt-4o",
        "anthropic": "claude-3-5-sonnet",
        "gemini": "gemini-3.5-flash-lite",
        "ollama": "llama3.1",
    }
    suggested_model = default_models.get(provider, "gpt-4o")
    model_name = questionary.text(
        "Model Name:",
        default=suggested_model,
    ).ask()
    if not model_name:
        model_name = suggested_model

    # 5. API Key
    api_key_input = questionary.text(
        "Provider API Key (leave empty to use environment variables):",
        default="",
    ).ask()
    api_key = api_key_input.strip() if api_key_input and api_key_input.strip() else None

    # Construct and save config
    config = ARCConfig(
        target_url=target_url,
        proxy_port=proxy_port,
        active_provider=provider,
        model_name=model_name,
        api_key=api_key,
    )

    init_arc_scaffold(root, config=config, overwrite=True)
    console.print("[green]✓ Created standard .arc/ layout and config.yaml[/green]")

    # 6. Post-init mining prompt
    should_mine = questionary.confirm(
        "Do you want to auto-mine invariants now?",
        default=True,
    ).ask()

    if should_mine:
        console.print("[dim]Scanning schemas and source code for invariants...[/dim]")
        mined_count = _trigger_quick_auto_mine(root)
        console.print(
            f"[green]✓ Invariant mining complete: {mined_count} candidates saved to .arc/catalog/mined_invariants.json[/green]"
        )

    return config


def run_edit_config_wizard(project_root: Path | None = None) -> ARCConfig:
    """Interactively edits existing .arc/config.yaml."""
    root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    config_file = root / ".arc" / "config.yaml"

    current_cfg = ARCConfig.load(config_file) if config_file.is_file() else ARCConfig()

    console.print(
        Panel.fit(
            f"[bold cyan]Edit ARC Configuration[/bold cyan]\nFile: [bold]{config_file}[/bold]",
            border_style="cyan",
        )
    )

    # 1. Target URL
    target_url = questionary.text(
        "Target Agent / Backend URL:",
        default=current_cfg.target_url,
    ).ask()
    if not target_url:
        target_url = current_cfg.target_url

    # 2. Proxy Port
    proxy_port_str = questionary.text(
        "ARC Debugger Proxy Port:",
        default=str(current_cfg.proxy_port),
    ).ask()
    proxy_port = (
        int(proxy_port_str)
        if proxy_port_str and proxy_port_str.isdigit()
        else current_cfg.proxy_port
    )

    # 3. Active Provider
    provider = questionary.select(
        "Active LLM Provider:",
        choices=["openai", "anthropic", "gemini", "ollama"],
        default=current_cfg.active_provider,
    ).ask()
    if not provider:
        provider = current_cfg.active_provider

    # 4. Model Name
    model_name = questionary.text(
        "Model Name:",
        default=current_cfg.model_name,
    ).ask()
    if not model_name:
        model_name = current_cfg.model_name

    # 5. API Key
    api_key_default = current_cfg.api_key or ""
    api_key_input = questionary.text(
        "Provider API Key (leave empty to keep current or use env):",
        default=api_key_default,
    ).ask()
    api_key = api_key_input.strip() if api_key_input and api_key_input.strip() else None

    updated_cfg = ARCConfig(
        target_url=target_url,
        proxy_port=proxy_port,
        active_provider=provider,
        model_name=model_name,
        api_key=api_key,
        telemetry_enabled=current_cfg.telemetry_enabled,
        trace_capture=current_cfg.trace_capture,
    )
    updated_cfg.save(config_file)
    console.print("[green]✓ Configuration updated successfully.[/green]")
    return updated_cfg


@init_app.callback(invoke_without_command=True)
def init_command(
    target_url: str | None = typer.Option(
        None, "--target-url", "-t", help="Target Agent or Backend URL"
    ),
    proxy_port: int = typer.Option(8089, "--port", "-p", help="ARC Debugger Proxy port"),
    provider: str = typer.Option("openai", "--provider", help="Active LLM provider"),
    model: str = typer.Option("gpt-4o", "--model", "-m", help="Active model name"),
) -> None:
    """Initializes ARC project layout and configuration."""
    cwd = Path.cwd()
    if target_url is not None:
        cfg = ARCConfig(
            target_url=target_url,
            proxy_port=proxy_port,
            active_provider=provider,
            model_name=model,
        )
        init_arc_scaffold(cwd, config=cfg, overwrite=True)
        console.print(f"[green]✓ Initialized .arc/ with target URL {target_url}[/green]")
    else:
        if is_arc_scaffold_initialized(cwd):
            run_edit_config_wizard(cwd)
        else:
            run_init_wizard(cwd)
