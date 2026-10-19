"""Unit tests for ARC directory scaffolding and configuration management.

Covers TASK-CLI-001 acceptance criteria:
- init_arc_scaffold directory creation (.arc, incidents, evidence, postmortems, catalog)
- postmortems/TEMPLATE.md structure and required fields
- ARCConfig Pydantic model validation and serialization
- Idempotency and environment detection
"""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from arc.cli.config import ARCConfig, find_config
from arc.cli.scaffold import (
    init_arc_scaffold,
    is_arc_scaffold_initialized,
)


def test_init_arc_scaffold_creates_structure(tmp_path: Path) -> None:
    """Verifies that init_arc_scaffold creates all required directories and templates."""
    assert not is_arc_scaffold_initialized(tmp_path)

    created_paths = init_arc_scaffold(tmp_path)
    assert is_arc_scaffold_initialized(tmp_path)
    assert created_paths["config_file"].is_file()

    arc_dir = tmp_path / ".arc"
    assert arc_dir.is_dir()
    assert (arc_dir / "incidents").is_dir()
    assert (arc_dir / "evidence" / "agent_faults").is_dir()
    assert (arc_dir / "evidence" / "backend_faults").is_dir()
    assert (arc_dir / "postmortems").is_dir()
    assert (arc_dir / "catalog").is_dir()

    # Verify template
    template_file = arc_dir / "postmortems" / "TEMPLATE.md"
    assert template_file.is_file()
    content = template_file.read_text(encoding="utf-8")
    for required_field in [
        "Incident Title",
        "Date",
        "Severity",
        "Root Cause",
        "Failed Action",
        "Action Items (Invariants)",
    ]:
        assert required_field in content, f"Missing required field '{required_field}' in TEMPLATE.md"

    # Verify config file
    config_file = arc_dir / "config.yaml"
    assert config_file.is_file()
    with open(config_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert data["proxy_port"] == 8089
    assert data["active_provider"] == "openai"
    assert data["telemetry_enabled"] is True
    assert "target_url" in data


def test_init_arc_scaffold_with_custom_config(tmp_path: Path) -> None:
    """Verifies init_arc_scaffold preserves custom configuration parameters."""
    custom_cfg = ARCConfig(
        target_url="http://agent.internal:3000",
        proxy_port=9090,
        active_provider="anthropic",
        model_name="claude-3-5-sonnet-20241022",
        telemetry_enabled=False,
    )

    init_arc_scaffold(tmp_path, config=custom_cfg)

    loaded_cfg = ARCConfig.load(tmp_path / ".arc" / "config.yaml")
    assert loaded_cfg.target_url == "http://agent.internal:3000"
    assert loaded_cfg.proxy_port == 9090
    assert loaded_cfg.active_provider == "anthropic"
    assert loaded_cfg.model_name == "claude-3-5-sonnet-20241022"
    assert loaded_cfg.telemetry_enabled is False


def test_init_arc_scaffold_idempotency(tmp_path: Path) -> None:
    """Verifies that re-running init does not overwrite existing config unless overwrite=True."""
    init_arc_scaffold(tmp_path)
    config_file = tmp_path / ".arc" / "config.yaml"

    # Modify config file
    config_file.write_text("proxy_port: 9999\ntarget_url: http://custom:5000\n", encoding="utf-8")

    # Re-run init without overwrite
    init_arc_scaffold(tmp_path, overwrite=False)
    assert "proxy_port: 9999" in config_file.read_text(encoding="utf-8")

    # Re-run init with overwrite
    init_arc_scaffold(tmp_path, overwrite=True)
    loaded = ARCConfig.load(config_file)
    assert loaded.proxy_port == 8089


def test_arc_config_validation() -> None:
    """Verifies ARCConfig validation constraints."""
    # Valid default config
    cfg = ARCConfig()
    assert cfg.proxy_port == 8089
    assert cfg.active_provider == "openai"

    # Invalid proxy port (< 1 or > 65535)
    with pytest.raises(ValidationError):
        ARCConfig(proxy_port=0)

    with pytest.raises(ValidationError):
        ARCConfig(proxy_port=70000)

    # Invalid target URL (must include scheme http/https)
    with pytest.raises(ValidationError):
        ARCConfig(target_url="localhost:8000")

    # Empty active provider
    with pytest.raises(ValidationError):
        ARCConfig(active_provider="")


def test_arc_config_save_load_roundtrip(tmp_path: Path) -> None:
    """Verifies ARCConfig roundtrip save and load to YAML."""
    config_file = tmp_path / "config.yaml"
    original = ARCConfig(
        target_url="https://api.myagent.ai",
        proxy_port=8089,
        active_provider="gemini",
        model_name="gemini-3.5-flash-lite",
        telemetry_enabled=True,
        trace_capture=True,
    )
    original.save(config_file)

    loaded = ARCConfig.load(config_file)
    assert loaded.target_url == original.target_url
    assert loaded.proxy_port == original.proxy_port
    assert loaded.active_provider == original.active_provider
    assert loaded.model_name == original.model_name
    assert loaded.telemetry_enabled == original.telemetry_enabled
    assert loaded.trace_capture == original.trace_capture


def test_find_config(tmp_path: Path) -> None:
    """Verifies find_config locates .arc/config.yaml upwards from nested paths."""
    nested_dir = tmp_path / "services" / "agent" / "handlers"
    nested_dir.mkdir(parents=True)

    assert find_config(nested_dir) is None

    init_arc_scaffold(tmp_path)
    found = find_config(nested_dir)
    assert found is not None
    assert found.resolve() == (tmp_path / ".arc" / "config.yaml").resolve()


def test_env_example_created(tmp_path: Path) -> None:
    """Verifies that .arc/.env.example is created with template variables."""
    paths = init_arc_scaffold(tmp_path)
    env_example = paths["env_example_file"]
    assert env_example.is_file()
    content = env_example.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=" in content
    assert "ANTHROPIC_API_KEY=" in content
    assert "GEMINI_API_KEY=" in content


def test_resolve_provider_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies resolve_provider_credentials reads config or environment variables."""
    from arc.cli.config import require_provider_credentials, resolve_provider_credentials

    # Clear env
    for k in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "ARC_API_KEY", "LLM_API_KEY"]:
        monkeypatch.delenv(k, raising=False)

    # 1. Config with explicit api_key
    cfg = ARCConfig(active_provider="openai", api_key="sk-explicit-config")
    assert resolve_provider_credentials(cfg, project_root=tmp_path) == "sk-explicit-config"

    # 2. Config without api_key, resolved from environment variable
    cfg_empty = ARCConfig(active_provider="anthropic", api_key=None)
    assert resolve_provider_credentials(cfg_empty, project_root=tmp_path) is None

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
    assert resolve_provider_credentials(cfg_empty, project_root=tmp_path) == "sk-ant-from-env"
    assert require_provider_credentials(cfg_empty, project_root=tmp_path) == "sk-ant-from-env"

    # 3. Missing credentials raise descriptive error
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="Missing API key for provider 'anthropic'"):
        require_provider_credentials(cfg_empty, project_root=tmp_path)
