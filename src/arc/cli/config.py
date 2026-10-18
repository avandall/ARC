"""Configuration management for ARC CLI.

Handles reading, validating, and persisting project-level ARC configuration
stored under `.arc/config.yaml`.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class ARCConfig(BaseModel):
    """Project-level ARC configuration model."""

    target_url: str = Field(
        default="http://localhost:8000",
        description="Target Agent or Backend HTTP endpoint URL.",
    )
    proxy_port: int = Field(
        default=8089,
        ge=1,
        le=65535,
        description="Port used by the ARC Debugger Proxy.",
    )
    active_provider: str = Field(
        default="openai",
        min_length=1,
        description="Active LLM provider (openai, anthropic, gemini, ollama, etc.).",
    )
    model_name: str = Field(
        default="gpt-4o",
        min_length=1,
        description="Active model name identifier.",
    )
    api_key: str | None = Field(
        default=None,
        description="Optional API key or secret token override.",
    )
    telemetry_enabled: bool = Field(
        default=True,
        description="Flag controlling OpenTelemetry and local telemetry collection.",
    )
    trace_capture: bool = Field(
        default=True,
        description="Flag controlling automatic execution trace capture.",
    )

    @field_validator("target_url")
    @classmethod
    def validate_target_url(cls, v: str) -> str:
        """Ensures target_url includes a valid HTTP/HTTPS scheme."""
        val = v.strip()
        if not val.startswith(("http://", "https://")):
            raise ValueError(f"target_url must start with http:// or https://, got: {v}")
        return val

    @field_validator("active_provider")
    @classmethod
    def validate_active_provider(cls, v: str) -> str:
        """Validates and standardizes active_provider string."""
        val = v.strip().lower()
        if not val:
            raise ValueError("active_provider cannot be empty")
        return val

    def to_yaml(self) -> str:
        """Serializes the configuration to a YAML string."""
        data: dict[str, Any] = self.model_dump()
        return str(yaml.safe_dump(data, sort_keys=False))

    @classmethod
    def from_yaml(cls, content: str) -> "ARCConfig":
        """Deserializes configuration from a YAML string."""
        loaded = yaml.safe_load(content)
        data = loaded if isinstance(loaded, dict) else {}
        return cls.model_validate(data)

    def save(self, path: Path | str) -> None:
        """Saves configuration to target file path."""
        target_path = Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(self.to_yaml(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | str) -> "ARCConfig":
        """Loads configuration from target file path."""
        target_path = Path(path)
        if not target_path.is_file():
            raise FileNotFoundError(f"Configuration file not found: {target_path}")
        return cls.from_yaml(target_path.read_text(encoding="utf-8"))


def find_config(start_path: Path | None = None) -> Path | None:
    """Traverses upward from start_path to locate .arc/config.yaml."""
    current = Path(start_path).resolve() if start_path else Path.cwd().resolve()
    while True:
        candidate = current / ".arc" / "config.yaml"
        if candidate.is_file():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


def get_arc_dir(project_root: Path | None = None) -> Path:
    """Returns the .arc directory path for a project root."""
    root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    return root / ".arc"
