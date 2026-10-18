"""Scaffolding generator for project-level .arc directory layout.

Creates and manages standard directory structures:
- .arc/config.yaml
- .arc/incidents/
- .arc/evidence/agent_faults/
- .arc/evidence/backend_faults/
- .arc/postmortems/TEMPLATE.md
- .arc/catalog/
"""

from pathlib import Path

from arc.cli.config import ARCConfig

DEFAULT_POSTMORTEM_TEMPLATE = """# Incident Postmortem Analysis

## Incident Title: [Brief descriptive summary of incident]
- **Date:** YYYY-MM-DD
- **Severity:** P0-Critical | P1-High | P2-Medium | P3-Low
- **Status:** Resolved / Action Items Pending

---

## 1. Executive Summary & Impact
Brief summary of the incident impact and affected systems.

## 2. Root Cause
Detailed technical explanation of the failure mechanism (e.g. missing idempotency key, timeout after commit, hallucinated parameter).

## 3. Failed Action
The exact agent or tool execution that failed:
- **Tool / Component:** `tool_name`
- **Input Parameters:** `{}`
- **Observed Behavior:** Description of failure

## 4. Timeline
- `HH:MM`: Incident detected
- `HH:MM`: Triage and investigation
- `HH:MM`: Mitigation applied

## 5. Action Items (Invariants)
- [ ] Define invariant rule to prevent recurrence: `INV-xxx`
- [ ] Add regression test in ARC chaos harness: `tests/...`
- [ ] Implement and verify fix
"""


def init_arc_scaffold(
    project_root: Path,
    config: ARCConfig | None = None,
    overwrite: bool = False,
) -> dict[str, Path]:
    """Initializes the standard `.arc/` directory scaffolding.

    Args:
        project_root: Base path of the target project.
        config: Optional pre-configured ARCConfig model. Defaults to ARCConfig().
        overwrite: When True, overwrites existing config and templates.

    Returns:
        Dictionary mapping layout identifiers to their respective Path instances.
    """
    root = Path(project_root).resolve()
    arc_dir = root / ".arc"
    incidents_dir = arc_dir / "incidents"
    evidence_agent_dir = arc_dir / "evidence" / "agent_faults"
    evidence_backend_dir = arc_dir / "evidence" / "backend_faults"
    postmortems_dir = arc_dir / "postmortems"
    catalog_dir = arc_dir / "catalog"

    for directory in [
        arc_dir,
        incidents_dir,
        evidence_agent_dir,
        evidence_backend_dir,
        postmortems_dir,
        catalog_dir,
    ]:
        directory.mkdir(parents=True, exist_ok=True)

    template_file = postmortems_dir / "TEMPLATE.md"
    if not template_file.exists() or overwrite:
        template_file.write_text(DEFAULT_POSTMORTEM_TEMPLATE, encoding="utf-8")

    config_file = arc_dir / "config.yaml"
    if not config_file.exists() or overwrite:
        effective_cfg = config or ARCConfig()
        effective_cfg.save(config_file)

    return {
        "arc_dir": arc_dir,
        "config_file": config_file,
        "incidents_dir": incidents_dir,
        "evidence_agent_dir": evidence_agent_dir,
        "evidence_backend_dir": evidence_backend_dir,
        "postmortems_dir": postmortems_dir,
        "template_file": template_file,
        "catalog_dir": catalog_dir,
    }


def is_arc_scaffold_initialized(project_root: Path) -> bool:
    """Checks whether the project root has an initialized .arc layout."""
    config_file = Path(project_root).resolve() / ".arc" / "config.yaml"
    return config_file.is_file()
