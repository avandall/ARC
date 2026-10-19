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


def load_env_file(project_root: Path | None = None) -> None:
    """Loads environment variables from .env in project root if present and not already set."""
    import os

    root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    for candidate in [root / ".env", root / ".arc" / ".env"]:
        if candidate.is_file():
            try:
                for line in candidate.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v
            except Exception:
                pass


def resolve_provider_credentials(
    config: ARCConfig | None = None,
    provider: str | None = None,
    project_root: Path | None = None,
) -> str | None:
    """Resolves API key for an LLM provider from config or environment variables.

    Lookup hierarchy:
      1. Explicit config.api_key (if non-empty)
      2. Environment variable specific to provider:
         - openai -> OPENAI_API_KEY
         - anthropic -> ANTHROPIC_API_KEY
         - gemini -> GEMINI_API_KEY or GOOGLE_API_KEY
         - ollama -> OLLAMA_API_KEY (optional)
      3. Generic environment variables: ARC_API_KEY, LLM_API_KEY
    """
    import os

    load_env_file(project_root)

    if config and config.api_key and config.api_key.strip():
        return config.api_key.strip()

    active = (provider or (config.active_provider if config else "openai")).strip().lower()

    provider_env_map = {
        "openai": ["OPENAI_API_KEY"],
        "anthropic": ["ANTHROPIC_API_KEY"],
        "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "ollama": ["OLLAMA_API_KEY"],
    }

    env_candidates = provider_env_map.get(active, []) + ["ARC_API_KEY", "LLM_API_KEY"]
    for env_var in env_candidates:
        val = os.getenv(env_var)
        if val and val.strip():
            return val.strip()

    return None


def require_provider_credentials(
    config: ARCConfig | None = None,
    provider: str | None = None,
    project_root: Path | None = None,
) -> str:
    """Resolves API key or raises a descriptive ValueError if not configured."""
    key = resolve_provider_credentials(config=config, provider=provider, project_root=project_root)
    if not key:
        active = (provider or (config.active_provider if config else "openai")).strip().lower()
        env_name = f"{active.upper()}_API_KEY"
        raise ValueError(
            f"Missing API key for provider '{active}'. Please set environment variable {env_name} "
            f"in your environment, in .env, or configure 'api_key' in .arc/config.yaml."
        )
    return key
