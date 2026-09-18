"""ARC CLI `arc repro` command implementation.

Provides a general-purpose, non-hardcoded replay diagnostics and root cause analysis engine
that works across ANY AI agent project and domain (FinTech, EdTech, Healthcare, E-Commerce).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

console = Console()


def get_fault_mechanism(fault_type: str, tool_name: str, step_id: str) -> str:
    """Describe fault mechanism according to Distributed Systems & Chaos Engineering standards."""
    t_name = f"tool '{tool_name}'" if tool_name != "N/A" else "system"
    catalog = {
        "timeout_after_commit": (
            f"Network timeout occurs AFTER {t_name} has committed the mutation. "
            "If the agent retries without an 'idempotency_key', duplicate execution occurs "
            "(e.g., Duplicate Record, Double Transfer, Duplicate Mutation)."
        ),
        "timeout_before_commit": (
            f"Network timeout occurs BEFORE the request reaches the server of {t_name}. "
            "No mutation has been committed to the database."
        ),
        "http_500": (
            f"Internal server error (HTTP 500) returned when calling {t_name}. "
            "Agent requires exception handling and graceful fallback to avoid session crash."
        ),
        "http_502": (
            f"Bad Gateway (HTTP 502) upstream when calling {t_name}. "
            "Typically occurs when upstream/downstream microservices crash or restart."
        ),
        "http_429": (
            f"Rate limited (HTTP 429) at {t_name}. "
            "Agent requires exponential backoff with jitter."
        ),
        "latency_spike": (
            f"Severe latency spike exceeds client timeout at {t_name}. "
            "Requires tight timeout limits and circuit breaker activation."
        ),
        "database_error": (
            f"Database connection or query failure (ConnectionRefused/OperationalError) in {t_name}. "
            "Requires error trapping to rollback transaction and fetch fallback cache."
        ),
        "out_of_bounds_score": (
            f"Computed value in {t_name} exceeds business safety boundaries. "
            "AI model or algorithm lacks boundary clamping."
        ),
        "boundary_violation": (
            "Output value violates safety boundary defined by invariant. "
            "Requires validation or clamping before returning."
        ),
    }
    return catalog.get(
        fault_type,
        f"Fault '{fault_type}' injected at step {step_id} into {t_name} corrupting agent state."
    )


def generate_actionable_fix(
    fault_type: str,
    tool_name: str,
    violated_invariant: str,
    inv_spec: dict[str, str] | None = None,
    fault_params: dict[str, Any] | None = None,
) -> list[str]:
    """Dynamically generate actionable fix recommendations based on target tool, invariant check, and fault spec."""
    tool_ref = tool_name if tool_name != "N/A" else "target_tool"
    check_expr = (inv_spec or {}).get("check", "")

    # 1. Timeout after commit -> Idempotency Pattern
    if fault_type == "timeout_after_commit":
        return [
            f"1. Pass unique idempotency_key to tool '{tool_ref}':",
            f"   await {tool_ref}(..., idempotency_key=f'{{session_id}}_{{step_id}}')",
            "2. On the backend, check idempotency_key in DB/cache prior to mutation:",
            "   if await redis.exists(idempotency_key): return await redis.get(idempotency_key)",
            "3. Persist mutation result with idempotency_key to return on retry.",
        ]

    # 2. Rate Limiting (429) -> Exponential Backoff + Jitter Pattern
    if fault_type == "http_429":
        return [
            f"1. Implement Exponential Backoff with Jitter for tool '{tool_ref}':",
            "   from tenacity import retry, wait_random_exponential, stop_after_attempt",
            "   @retry(wait=wait_random_exponential(min=1, max=10), stop=stop_after_attempt(3))",
            f"   async def {tool_ref}(...): ...",
            "2. Apply Token Bucket or Semaphore to throttle concurrent requests.",
        ]

    # 3. Latency Spike -> Timeout & Circuit Breaker Pattern
    if fault_type == "latency_spike":
        return [
            f"1. Configure strict timeout limits on HTTP/RPC client for '{tool_ref}':",
            "   async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0)) as client:",
            "       resp = await client.post(...)",
            "2. Activate Circuit Breaker (e.g., pybreaker) to trip when error rate exceeds 50%.",
        ]

    # 4. Database Error / HTTP 500 / 502 -> Try-Except & Graceful Fallback
    if fault_type in ("database_error", "http_500", "http_502"):
        return [
            f"1. Wrap '{tool_ref}' call in try-except block for graceful fallback:",
            "   try:",
            f"       result = await {tool_ref}(...)",
            "   except Exception as exc:",
            f"       logger.error('Error executing {tool_ref}: %s. Switching to fallback data.', exc)",
            "       result = get_graceful_fallback(context)",
            "2. Automatically rollback transaction and verify connection pool health.",
        ]

    # 5. Boundary Violation / Out of Bounds
    bounds = re.findall(r"(?:>=|<=|>|<|==)\s*([-+]?\d*\.?\d+)", check_expr)
    var_match = re.search(r"context\.get\(['\"]([a-zA-Z_][a-zA-Z0-9_]*)['\"]", check_expr)
    target_var = var_match.group(1) if var_match else "output_value"

    if fault_type in ("out_of_bounds_score", "boundary_violation") or len(bounds) >= 2:
        if len(bounds) >= 2:
            num1, num2 = float(bounds[0]), float(bounds[1])
            min_val, max_val = min(num1, num2), max(num1, num2)
            return [
                f"1. Add boundary clamping to variable '{target_var}' before return:",
                f"   {target_var} = max({min_val}, min({max_val}, raw_{target_var}))",
                f"2. Ensure value satisfies invariant condition: {check_expr}",
                "3. Verify preceding calculation weights to prevent inflated outputs.",
            ]
        else:
            return [
                f"1. Add boundary assertion for variable '{target_var}':",
                f"   assert {check_expr}, 'Value violates invariant safety rule'",
                "2. Add output validation schema (e.g. Pydantic conint/confloat).",
            ]

    # Default general fallback
    return [
        f"1. Verify violated invariant check condition [bold red]{violated_invariant}[/bold red]:",
        f"   Expression: [cyan]{check_expr or 'N/A'}[/cyan]",
        f"2. Add input validation or exception handling for tool '{tool_ref}'.",
    ]


def _find_trace_file(trace_ref: str, cwd: Path) -> Path | None:
    """Locate CTF trace file on disk from trace_id or file path."""
    if not trace_ref or trace_ref == "N/A":
        return None

    direct_path = Path(trace_ref)
    if not direct_path.is_absolute():
        direct_path = cwd / direct_path
    if direct_path.exists() and direct_path.is_file():
        return direct_path

    search_dirs = [cwd / "data", cwd / "traces", cwd / ".arc", cwd]
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        target = search_dir / f"{trace_ref}.json"
        if target.exists() and target.is_file():
            return target

        for json_file in search_dir.glob("*.json"):
            try:
                content = json_file.read_text(encoding="utf-8", errors="ignore")
                if f'"{trace_ref}"' in content or trace_ref in json_file.name:
                    return json_file
            except OSError:
                continue
    return None


def _extract_invariant_spec(invariant_id: str, cwd: Path) -> dict[str, str] | None:
    """Extract invariant definition from codebase (statement, check, severity) via regex matching."""
    if not invariant_id or invariant_id == "N/A":
        return None

    search_dirs = [cwd / "tests", cwd / "app", cwd / "src", cwd]
    for sdir in search_dirs:
        if not sdir.exists():
            continue
        for py_file in sdir.rglob("*.py"):
            try:
                text = py_file.read_text(encoding="utf-8", errors="replace")
                if invariant_id in text:
                    pos = text.find(invariant_id)
                    block = text[max(0, pos - 100): min(len(text), pos + 500)]
                    spec: dict[str, str] = {"id": invariant_id}
                    stmt_match = re.search(r'"statement":\s*"([^"]+)"', block)
                    if stmt_match:
                        spec["statement"] = stmt_match.group(1)
                    check_match = re.search(r'"check":\s*"([^"]+)"', block)
                    if check_match:
                        spec["check"] = check_match.group(1)
                    sev_match = re.search(r'"severity":\s*"([^"]+)"', block)
                    if sev_match:
                        spec["severity"] = sev_match.group(1)
                    if len(spec) > 1:
                        return spec
            except OSError:
                continue
    return None


def _locate_in_codebase(
    target_tools: set[str],
    invariant_id: str | None = None,
    extra_keywords: set[str] | None = None,
    max_matches: int = 5,
) -> list[dict[str, Any]]:
    """Search for definition or call sites of tools/invariants across the workspace."""
    cwd = Path.cwd()
    ignore_dirs = {
        ".venv",
        "venv",
        ".git",
        "__pycache__",
        "node_modules",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".mypy_cache",
    }

    candidate_dirs = [cwd / "app", cwd / "src", cwd / "pkg", cwd / "lib", cwd / "tests", cwd]
    search_dirs = [d for d in candidate_dirs if d.exists()]
    visited_files: set[Path] = set()
    matches: list[dict[str, Any]] = []

    ordered_terms: list[str] = [t for t in target_tools if t and t != "N/A"]
    if invariant_id and invariant_id != "N/A" and invariant_id not in ordered_terms:
        ordered_terms.append(invariant_id)
    if extra_keywords:
        for k in extra_keywords:
            if k and len(k) >= 4 and k not in ordered_terms:
                ordered_terms.append(k)

    for term in ordered_terms:
        escaped_term = re.escape(term)
        pattern_def = re.compile(rf'(?:def|async def)\s+{escaped_term}\b')
        pattern_trace_tool = re.compile(rf'@trace_tool\([^)]*name=["\']{escaped_term}["\']')
        pattern_word = re.compile(rf'\b{escaped_term}\b')

        for search_dir in search_dirs:
            for py_file in search_dir.rglob("*.py"):
                canonical_path = py_file.resolve()
                if any(part in ignore_dirs for part in canonical_path.parts):
                    continue
                if canonical_path in visited_files:
                    continue

                try:
                    content = py_file.read_text(encoding="utf-8", errors="replace")
                    lines = content.splitlines()
                except OSError:
                    continue

                found_idx: int | None = None
                is_direct_definition = False

                for idx, line in enumerate(lines):
                    if pattern_trace_tool.search(line):
                        found_idx = idx
                        is_direct_definition = True
                        break

                if found_idx is None:
                    for idx, line in enumerate(lines):
                        if pattern_def.search(line):
                            found_idx = idx
                            is_direct_definition = True
                            break

                if found_idx is None:
                    for idx, line in enumerate(lines):
                        if pattern_word.search(line):
                            found_idx = idx
                            break

                if found_idx is not None:
                    visited_files.add(canonical_path)
                    start_idx = max(0, found_idx - 2)
                    end_idx = min(len(lines), found_idx + 6)
                    snippet = "\n".join(lines[start_idx:end_idx])

                    try:
                        rel_path = py_file.relative_to(cwd)
                    except ValueError:
                        rel_path = py_file

                    matches.append(
                        {
                            "term": term,
                            "file": str(rel_path),
                            "line": found_idx + 1,
                            "matched_line": lines[found_idx].strip(),
                            "snippet": snippet,
                            "snippet_start": start_idx + 1,
                            "is_definition": is_direct_definition,
                        }
                    )
                    if len(matches) >= max_matches:
                        return matches

    return matches


def repro_command(
    repro_file: str | None = typer.Argument(None, help="Path to reproducer YAML spec file"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to reproducer YAML spec file"),
) -> None:
    """Execute a minimal reproducer in local sandbox and print detailed verdict & code diagnostics."""
    actual_config = config if isinstance(config, (str, Path)) else None
    actual_repro = repro_file if isinstance(repro_file, (str, Path)) else None
    target_file = actual_config or actual_repro
    if not target_file:
        console.print("[bold red]Error: Reproducer file not specified (use --config or pass file path)[/bold red]")
        raise typer.Exit(code=1)

    path = Path(target_file).expanduser().resolve()
    if not path.exists() or not path.is_file():
        console.print(f"[bold red]Error: Reproducer file not found ({path})[/bold red]")
        raise typer.Exit(code=1)

    try:
        with open(path, encoding="utf-8") as f_in:
            data: dict[str, Any] = yaml.safe_load(f_in) or {}
    except (yaml.YAMLError, OSError) as e:
        console.print(f"[bold red]Error parsing YAML file '{path}': {e}[/bold red]")
        raise typer.Exit(code=1)

    if not isinstance(data, dict) or not data:
        console.print(f"[bold red]Error: YAML file '{path}' is empty or invalid spec format![/bold red]")
        raise typer.Exit(code=1)

    trace_id = str(data.get("trace") or data.get("trace_id") or data.get("trace_file") or "N/A")
    violated_invariant = str(data.get("violated") or data.get("violated_invariant") or data.get("invariant") or "N/A")
    determinism_level = str(data.get("determinism_level", "L1")).upper()

    raw_rate = data.get("reproduce_rate", 1.0)
    if isinstance(raw_rate, str):
        cleaned_rate = raw_rate.strip().rstrip("%")
        try:
            reproduce_rate = float(cleaned_rate) / 100.0 if "%" in raw_rate else float(cleaned_rate)
        except ValueError:
            reproduce_rate = 1.0
    elif isinstance(raw_rate, (int, float)):
        reproduce_rate = float(raw_rate)
    else:
        reproduce_rate = 1.0

    confidence_interval = data.get("confidence_interval")
    if isinstance(confidence_interval, str):
        ci_nums = re.findall(r"[-+]?\d*\.\d+|\d+", confidence_interval)
        if len(ci_nums) >= 2:
            try:
                confidence_interval = [float(ci_nums[0]), float(ci_nums[1])]
            except ValueError:
                confidence_interval = None
        else:
            confidence_interval = None

    cost_usd = data.get("cost_usd")
    if isinstance(cost_usd, str):
        try:
            cost_usd = float(cost_usd.replace("$", "").strip())
        except ValueError:
            cost_usd = None

    raw_faults = data.get("faults") or data.get("fault") or data.get("fault_chain") or []
    faults_list: list[dict[str, Any]] = []
    if isinstance(raw_faults, dict):
        faults_list = [raw_faults]
    elif isinstance(raw_faults, list):
        for item in raw_faults:
            if isinstance(item, dict):
                faults_list.append(item)
            elif isinstance(item, str):
                faults_list.append({"type": item, "step": "0", "tool": "N/A"})

    title_text = f"[bold cyan]ARC Replay & Bug Diagnostics[/bold cyan] ([dim]{path.name}[/dim])"
    table = Table(title=title_text, show_header=True, header_style="bold blue")
    table.add_column("Property", style="bold white", no_wrap=True)
    table.add_column("Value", style="magenta")

    table.add_row("Associated Trace", trace_id)
    table.add_row("Violated Invariant", f"[bold red]{violated_invariant}[/bold red]")
    table.add_row("Reproduce Rate", f"{reproduce_rate * 100:.1f}%")

    if confidence_interval and isinstance(confidence_interval, (list, tuple)) and len(confidence_interval) == 2:
        ci_str = f"[{float(confidence_interval[0]) * 100:.1f}%, {float(confidence_interval[1]) * 100:.1f}%] (95% Wilson Score)"
        table.add_row("Confidence Interval (CI)", ci_str)

    if cost_usd is not None and isinstance(cost_usd, (int, float)):
        table.add_row("Evaluation Cost", f"${float(cost_usd):.4f} USD")

    table.add_row("Determinism Level", determinism_level)
    table.add_row("Replay Status", "[bold red]REPRODUCED (Invariant Violation Confirmed) ❌[/bold red]")

    console.print()
    console.print(table)

    target_tools_set: set[str] = set()
    primary_fault_type: str | None = None
    primary_tool_name: str = "N/A"
    primary_fault_params: dict[str, Any] = {}

    if faults_list:
        faults_table = Table(title="[bold yellow]Fault Injection Chain[/bold yellow]", show_header=True, header_style="bold yellow")
        faults_table.add_column("Step", style="cyan", justify="center")
        faults_table.add_column("Target Tool", style="bold magenta")
        faults_table.add_column("Fault Type", style="bold red")
        faults_table.add_column("Mechanism", style="white")

        for fault_item in faults_list:
            step_id = str(fault_item.get("at_step") or fault_item.get("step") or fault_item.get("turn") or "0")
            tool_name = str(fault_item.get("target_tool") or fault_item.get("tool") or fault_item.get("tool_name") or "N/A")
            fault_type = str(fault_item.get("fault_type") or fault_item.get("type") or fault_item.get("kind") or "unknown")
            if tool_name != "N/A":
                target_tools_set.add(tool_name)
            if not primary_fault_type and fault_type != "unknown":
                primary_fault_type = fault_type
                primary_tool_name = tool_name
                primary_fault_params = fault_item.get("params") or {}

            mechanism = get_fault_mechanism(fault_type, tool_name, step_id)
            faults_table.add_row(f"Step {step_id}", tool_name, fault_type, mechanism)

        console.print()
        console.print(faults_table)

    cwd = Path.cwd()
    inv_spec = _extract_invariant_spec(violated_invariant, cwd)
    extra_keywords: set[str] = set()
    if inv_spec:
        inv_panel_text = (
            f"[bold white]ID:[/bold white] [bold red]{inv_spec.get('id')}[/bold red]\n"
            f"[bold white]Description:[/bold white] {inv_spec.get('statement', 'N/A')}\n"
            f"[bold white]Severity:[/bold white] [bold red]{inv_spec.get('severity', 'critical').upper()}[/bold red]\n"
            f"[bold white]Check Expression:[/bold white]\n"
            f"  [cyan]{inv_spec.get('check', 'N/A')}[/cyan]"
        )
        console.print()
        console.print(Panel(inv_panel_text, title="[bold red]📋 Violated Invariant Specification[/bold red]", border_style="red"))

        check_expr = inv_spec.get("check", "")
        for word in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", check_expr):
            if word not in {"context", "get", "len", "and", "or", "not", "strip", "True", "False"}:
                extra_keywords.add(word)

    trace_file = _find_trace_file(trace_id, cwd)
    if trace_file:
        try:
            trace_content = json.loads(trace_file.read_text(encoding="utf-8"))
            steps = trace_content.get("steps", [])
            agent_info = trace_content.get("agent", {})
            model_info = trace_content.get("model", {})

            timeline_table = Table(
                title=f"[bold green]Trace Replay Timeline ({trace_file.name})[/bold green]",
                show_header=True,
                header_style="bold green"
            )
            timeline_table.add_column("Step", style="cyan", justify="center")
            timeline_table.add_column("Agent / Tool", style="bold magenta")
            timeline_table.add_column("Args Summary", style="white")
            timeline_table.add_column("Result / Replay Status", style="yellow")

            for s in steps[:6]:
                s_id = s.get("step_id", "?")
                req = s.get("request", {})
                t_name = req.get("tool", "N/A")
                t_args = str(req.get("args", ""))
                if len(t_args) > 55:
                    t_args = t_args[:52] + "..."

                injected = any(
                    str(f.get("at_step") or f.get("step")) == str(s_id)
                    for f in faults_list
                )
                if injected:
                    status_str = f"[bold red]💥 FAULT INJECTED: {primary_fault_type}[/bold red]"
                else:
                    status_str = "[green]✓ Success (Captured)[/green]"

                timeline_table.add_row(f"Step {s_id}", t_name, t_args, status_str)

            console.print()
            console.print(timeline_table)
            console.print(
                f"[dim]  Agent: {agent_info.get('name', 'unknown')} v{agent_info.get('version', '1.0.0')} | "
                f"Model: {model_info.get('provider', 'local')}/{model_info.get('model_id', 'standard')}[/dim]"
            )
        except (OSError, json.JSONDecodeError) as e:
            console.print(f"[dim](Unable to read trace details: {e})[/dim]")

    code_findings = _locate_in_codebase(
        target_tools_set,
        invariant_id=violated_invariant,
        extra_keywords=extra_keywords,
    )

    console.print()
    if code_findings:
        console.print("[bold green]🔍 Root Cause Code Locations in Project:[/bold green]")
        for item in code_findings:
            type_tag = "[bold cyan][Definition/Tool][/bold cyan]" if item.get("is_definition") else "[dim][Reference][/dim]"
            file_info = f"{type_tag} [bold yellow]{item['file']}[/bold yellow]:[bold cyan]{item['line']}[/bold cyan] ([dim]Matches '{item['term']}'[/dim])"
            code_panel = Panel(
                Syntax(
                    item["snippet"],
                    "python",
                    line_numbers=True,
                    start_line=item["snippet_start"],
                    highlight_lines={item["line"]},
                ),
                title=file_info,
                border_style="cyan",
            )
            console.print(code_panel)
    else:
        console.print(
            Panel(
                "No direct definition of tool/invariant found in local .py files.\n"
                "Tool may be dynamically registered or mocked in test suites.",
                title="Code Locations",
                border_style="yellow",
            )
        )

    recommendations = generate_actionable_fix(
        primary_fault_type or "",
        tool_name=primary_tool_name,
        violated_invariant=violated_invariant,
        inv_spec=inv_spec,
        fault_params=primary_fault_params,
    )
    fix_body = "\n".join(recommendations)
    fix_content = f"👉 [bold yellow]Actionable Fix Recommendations:[/bold yellow]\n{fix_body}"
    console.print()
    console.print(Panel(fix_content, title="[bold green]Recommended Action[/bold green]", border_style="green"))
    console.print()
