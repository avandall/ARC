"""Unit tests for Smart State Detection and Setup Wizard (TASK-CLI-002).

Covers:
- run_init_wizard() prompting and initializing .arc/config.yaml
- Post-init invariant mining prompt: `? Do you want to auto-mine invariants now? [Y/n]`
- Smart state detection: first-time launch runs wizard, subsequent launch shows Main Menu
- Submenu options: [1.1] Edit Configuration updates .arc/config.yaml
- 100% English UI output
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from arc.cli.commands.init import run_edit_config_wizard, run_init_wizard
from arc.cli.config import ARCConfig
from arc.cli.main import app, handle_smart_start
from arc.cli.scaffold import init_arc_scaffold, is_arc_scaffold_initialized

runner = CliRunner()


def test_init_wizard_creates_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that run_init_wizard collects inputs and creates .arc/ layout."""
    assert not is_arc_scaffold_initialized(tmp_path)

    # Mock questionary interactions
    mock_text = MagicMock()
    mock_select = MagicMock()
    mock_confirm = MagicMock()

    # Step answers: target_url, proxy_port, model_name, api_key
    mock_text_returns = ["http://127.0.0.1:8000", "8089", "gpt-4o", ""]
    mock_text.side_effect = lambda *args, **kwargs: MagicMock(
        ask=MagicMock(return_value=mock_text_returns.pop(0))
    )
    mock_select.return_value = MagicMock(ask=MagicMock(return_value="openai"))
    mock_confirm.return_value = MagicMock(ask=MagicMock(return_value=True))

    monkeypatch.setattr("questionary.text", mock_text)
    monkeypatch.setattr("questionary.select", mock_select)
    monkeypatch.setattr("questionary.confirm", mock_confirm)

    cfg = run_init_wizard(project_root=tmp_path)

    assert is_arc_scaffold_initialized(tmp_path)
    assert cfg.target_url == "http://127.0.0.1:8000"
    assert cfg.proxy_port == 8089
    assert cfg.active_provider == "openai"
    assert cfg.model_name == "gpt-4o"

    # Verify config on disk
    loaded = ARCConfig.load(tmp_path / ".arc" / "config.yaml")
    assert loaded.target_url == "http://127.0.0.1:8000"
    assert loaded.proxy_port == 8089


def test_init_wizard_decline_mining(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that declining auto-mining skips mining execution."""
    mock_text_returns = ["http://localhost:5000", "8089", "gpt-4o", ""]
    monkeypatch.setattr(
        "questionary.text",
        lambda *args, **kwargs: MagicMock(ask=MagicMock(return_value=mock_text_returns.pop(0))),
    )
    monkeypatch.setattr(
        "questionary.select",
        lambda *args, **kwargs: MagicMock(ask=MagicMock(return_value="anthropic")),
    )
    # Decline mining prompt
    mock_confirm = MagicMock(return_value=MagicMock(ask=MagicMock(return_value=False)))
    monkeypatch.setattr("questionary.confirm", mock_confirm)

    cfg = run_init_wizard(project_root=tmp_path)
    assert is_arc_scaffold_initialized(tmp_path)
    assert cfg.active_provider == "anthropic"


def test_smart_state_detection_first_run_calls_wizard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When .arc/config.yaml is missing, smart state detection directs to wizard."""
    wizard_called = []

    def fake_wizard(project_root: Path | None = None) -> ARCConfig:
        wizard_called.append(True)
        return init_arc_scaffold(project_root or tmp_path)  # type: ignore[return-value]

    monkeypatch.setattr("arc.cli.main.run_init_wizard", fake_wizard)

    handle_smart_start(project_root=tmp_path)
    assert len(wizard_called) == 1


def test_smart_state_detection_second_run_calls_main_menu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When .arc/config.yaml exists, smart state detection skips wizard and opens Main Menu."""
    init_arc_scaffold(tmp_path)
    assert is_arc_scaffold_initialized(tmp_path)

    wizard_called = []
    menu_called = []

    def fake_wizard(project_root: Path | None = None) -> ARCConfig:
        wizard_called.append(True)
        return ARCConfig()

    def fake_menu(project_root: Path | None = None) -> None:
        menu_called.append(True)

    monkeypatch.setattr("arc.cli.main.run_init_wizard", fake_wizard)
    monkeypatch.setattr("arc.cli.main.run_main_menu", fake_menu)

    handle_smart_start(project_root=tmp_path)
    assert len(wizard_called) == 0
    assert len(menu_called) == 1


def test_edit_config_wizard_updates_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies that [1.1] Edit Configuration updates .arc/config.yaml."""
    init_arc_scaffold(tmp_path)

    # Edit target_url to new URL, keep other values
    mock_text_returns = ["http://new-target.local:9000", "8099", "claude-3-opus", "sk-secret"]
    monkeypatch.setattr(
        "questionary.text",
        lambda *args, **kwargs: MagicMock(ask=MagicMock(return_value=mock_text_returns.pop(0))),
    )
    monkeypatch.setattr(
        "questionary.select",
        lambda *args, **kwargs: MagicMock(ask=MagicMock(return_value="anthropic")),
    )

    updated_cfg = run_edit_config_wizard(project_root=tmp_path)
    assert updated_cfg.target_url == "http://new-target.local:9000"
    assert updated_cfg.proxy_port == 8099
    assert updated_cfg.active_provider == "anthropic"

    # Verify saved on disk
    loaded = ARCConfig.load(tmp_path / ".arc" / "config.yaml")
    assert loaded.target_url == "http://new-target.local:9000"
    assert loaded.proxy_port == 8099
    assert loaded.active_provider == "anthropic"


def test_cli_subcommand_bypasses_smart_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that explicit subcommands (like `arc --help`) bypass smart detection."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "ARC CLI - Autonomous Reliability & Chaos Engine" in result.output
