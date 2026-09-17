"""ARC CLI `arc catalog` command implementation (TASK-P3-004).

Provides interactive candidate review (`arc catalog review`) and candidate reconsideration (`arc catalog reconsider`).
"""

from __future__ import annotations

import sys
from typing import Any

import typer
from approval_gateway.gateway import ApprovalGateway
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from warehouse.db_store import DatabaseStore

catalog_app = typer.Typer(
    name="catalog",
    help="Property Catalog & Invariant Candidate Management",
    add_completion=False,
)

console = Console()
_db_store = DatabaseStore.get_shared_instance()
_gateway = ApprovalGateway(db_store=_db_store)


@catalog_app.command("review")
def review_command(
    candidate_id: str | None = typer.Option(
        None, "--id", "-i", help="Specific candidate ID to review"
    ),
    accept: bool = typer.Option(False, "--accept", "-a", help="Accept candidate non-interactively"),
    reject: bool = typer.Option(False, "--reject", "-r", help="Reject candidate non-interactively"),
    reason: str | None = typer.Option(
        None, "--reason", "-m", help="Reason for rejection (non-interactive)"
    ),
    statement: str | None = typer.Option(
        None, "--statement", "-s", help="Candidate statement if not in DB"
    ),
) -> None:
    """Interactive CLI review interface for pending invariant candidates (Accept, Edit, Reject)."""
    # Fetch target candidate or list pending candidates
    candidates: list[dict[str, Any]] = []
    if candidate_id:
        cand = _db_store.get_candidate(candidate_id)
        if cand:
            candidates.append(cand)
        elif statement:
            candidates.append({
                "candidate_id": candidate_id,
                "statement": statement,
                "category": "safety",
                "check_expr": statement,
                "status": "pending",
            })
        else:
            # Synthetic entry for candidate ID
            candidates.append({
                "candidate_id": candidate_id,
                "statement": f"Candidate {candidate_id}",
                "category": "safety",
                "check_expr": "",
                "status": "pending",
            })
    else:
        candidates = _db_store.list_candidates(status="pending")

    if not candidates and not candidate_id:
        console.print("[bold yellow]No pending invariant candidates found for review.[/bold yellow]")
        return

    # Non-interactive quick actions (useful for test automation & scripts)
    if accept and candidates:
        target = candidates[0]
        cid = target.get("candidate_id") or target.get("id", "cand_unknown")
        _db_store.update_candidate_status(cid, "approved")
        console.print(f"[bold green]Candidate '{cid}' ACCEPTED and marked as approved.[/bold green]")
        return

    if reject and candidates:
        target = candidates[0]
        cid = target.get("candidate_id") or target.get("id", "cand_unknown")
        rej_reason = reason or "Rejected via CLI command"
        stmt = target.get("statement") or statement or cid
        res = _gateway.reject_candidate(
            candidate_id=cid,
            reason=rej_reason,
            rejected_by="engineer",
            candidate_statement=stmt,
        )
        console.print(
            f"[bold red]Candidate '{cid}' REJECTED.[/bold red] "
            f"Statement Hash: [cyan]{res['statement_hash']}[/cyan]"
        )
        return

    # Interactive review loop
    for cand in candidates:
        cid = cand.get("candidate_id") or cand.get("id", "cand_unknown")
        c_stmt = cand.get("statement", "")
        c_cat = cand.get("category", "safety")
        c_check = cand.get("check_expr") or cand.get("check", "")
        c_sev = cand.get("severity", "critical")

        table = Table(title=f"Invariant Candidate: {cid}", show_header=True, header_style="bold magenta")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="white")
        table.add_row("ID", cid)
        table.add_row("Category", c_cat)
        table.add_row("Statement", c_stmt)
        table.add_row("Check Expression", c_check)
        table.add_row("Severity", c_sev)

        console.print(Panel(table, title="[bold blue]ARC Property Catalog Review[/bold blue]"))

        if not sys.stdin.isatty() and not (accept or reject):
            console.print(f"[dim]Non-interactive terminal detected. Skipping prompt for {cid}.[/dim]")
            continue

        choice = Prompt.ask(
            "Action for candidate",
            choices=["accept", "edit", "reject", "skip"],
            default="accept",
        )

        if choice == "accept":
            _db_store.update_candidate_status(cid, "approved")
            console.print(f"[bold green]Candidate '{cid}' APPROVED.[/bold green]")
        elif choice == "edit":
            new_check = Prompt.ask("Enter updated check expression", default=c_check)
            cand["check_expr"] = new_check
            cand["check"] = new_check
            _db_store.insert_candidate(cand)
            console.print(f"[bold yellow]Candidate '{cid}' updated with new expression.[/bold yellow]")
        elif choice == "reject":
            rej_reason = Prompt.ask("Enter rejection reason", default="Invalid domain constraint")
            res = _gateway.reject_candidate(
                candidate_id=cid,
                reason=rej_reason,
                rejected_by="engineer",
                candidate_statement=c_stmt,
            )
            console.print(
                f"[bold red]Candidate '{cid}' REJECTED.[/bold red] "
                f"Recorded Hash: [cyan]{res['statement_hash']}[/cyan]"
            )
        elif choice == "skip":
            console.print(f"[dim]Skipped {cid}.[/dim]")


@catalog_app.command("reconsider")
def reconsider_command(
    statement_hash: str = typer.Option(
        ...,
        "--hash",
        "-h",
        help="Normalized SHA-256 statement hash to remove from rejected_candidates",
    ),
) -> None:
    """Removes a statement hash from rejected_candidates (§8.3), allowing future reconsideration."""
    if not statement_hash:
        console.print("[bold red]Error: --hash parameter is required.[/bold red]")
        raise typer.Exit(code=1)

    removed = _db_store.remove_rejected_candidate(statement_hash)
    if removed:
        console.print(
            f"[bold green]Successfully removed statement hash '[cyan]{statement_hash}[/cyan]' "
            "from rejected_candidates table.[/bold green]"
        )
    else:
        # Also report success or message if no record found (idempotent delete)
        console.print(
            f"[yellow]Statement hash '[cyan]{statement_hash}[/cyan]' was not present in rejected_candidates table.[/yellow]"
        )
