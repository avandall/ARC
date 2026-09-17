"""Isolated Sandbox Runner for Docker internal network and UDS execution environments."""

from __future__ import annotations

import uuid
from typing import Any, NamedTuple

from arc.execution.sandbox_runner.passive_ledger import (
    PassiveEffectLedger,
    is_mutating_tool,
)
from arc.execution.sandbox_runner.security import (
    InvalidSignatureError,
    scan_credentials,
    verify_bundle_signature,
)


class NetworkConfig(NamedTuple):
    """Network configuration parameters for container sandbox."""

    name: str
    internal: bool
    gateway_allowed: bool


class SandboxConfig:
    """Sandbox configuration settings."""

    def __init__(
        self,
        network_mode: str = "arc-isolated-net",
        internal_network: bool = True,
        uds_socket_path: str = "/var/run/arc-proxy.sock",
        proxy_url: str = "http://arc-proxy:8089",
        mock_credentials: dict[str, str] | None = None,
        bundle_secret: str | None = None,
        bundle_signature: str | None = None,
    ) -> None:
        self.network_mode = network_mode
        self.internal_network = internal_network
        self.uds_socket_path = uds_socket_path
        self.proxy_url = proxy_url
        self.mock_credentials = mock_credentials or {
            "API_KEY": "mock_arc_key_test",
            "ENVIRONMENT": "sandbox",
        }
        self.bundle_secret = bundle_secret
        self.bundle_signature = bundle_signature
        self.network_config = NetworkConfig(
            name=network_mode,
            internal=internal_network,
            gateway_allowed=not internal_network,
        )


class SandboxContainer:
    """Represents an isolated sandbox execution container instance."""

    def __init__(
        self,
        container_id: str,
        config: SandboxConfig,
        ledger: PassiveEffectLedger,
        env: dict[str, str],
    ) -> None:
        self.container_id = container_id
        self.config = config
        self.ledger = ledger
        self.env = env
        self.is_running = True

    def execute_request(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: Any = None,
        timeout_seconds: float = 1.0,
    ) -> dict[str, Any]:
        """Executes an HTTP request within the container network scope.

        Raises TimeoutError / ConnectionError if request attempts external internet access
        (Egress Denied).
        """
        if not self.is_running:
            msg = "Container is stopped"
            raise RuntimeError(msg)

        # Check for external egress attempts (non-proxy domain or public IP)
        allowed_targets = {
            "http://arc-proxy:8089",
            "arc-proxy:8089",
            "arc-proxy",
            "localhost",
            "127.0.0.1",
            self.config.proxy_url,
            self.config.uds_socket_path,
        }

        url_clean = url.rstrip("/")
        is_allowed = any(url_clean.startswith(target) for target in allowed_targets)

        if not is_allowed:
            # External network call blocked at bridge level
            msg = (
                f"Egress Denied: Outbound request to '{url}' blocked by isolated network bridge "
                f"(network: '{self.config.network_mode}', internal: {self.config.internal_network})"
            )
            raise TimeoutError(msg)

        return {
            "status": "connected",
            "proxy": self.config.proxy_url,
            "network_mode": self.config.network_mode,
            "url": url,
            "method": method,
        }

    def execute_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Executes a tool call inside the sandbox.

        Mutating calls are trapped into the Passive Effect Ledger.
        """
        if not self.is_running:
            msg = "Container is stopped"
            raise RuntimeError(msg)

        if is_mutating_tool(tool_name):
            return self.ledger.trap_mutating_call(tool_name, args)

        return {
            "status": "ok",
            "tool_name": tool_name,
            "result": f"Read-only execution of '{tool_name}' completed",
        }

    def stop(self) -> None:
        """Stops the sandbox container."""
        self.is_running = False


class SandboxRunner:
    """Sandbox Runner managing container initialization, network isolation, credential injection,

    security scanning, and passive effect ledger trapping.
    """

    def __init__(
        self,
        config: SandboxConfig | None = None,
        ledger: PassiveEffectLedger | None = None,
    ) -> None:
        self.config = config or SandboxConfig()
        self.ledger = ledger or PassiveEffectLedger()

    def start_container(
        self,
        env: dict[str, str] | None = None,
        bundle_data: Any = None,
        signature: str | None = None,
        secret: str | None = None,
    ) -> SandboxContainer:
        """Starts a sandbox container after verifying signature and credential security.

        Raises:
            InvalidSignatureError: If HMAC signature verification fails.
            SecurityViolationError: If production credentials are detected.
        """
        effective_secret = secret or self.config.bundle_secret
        effective_sig = signature or self.config.bundle_signature

        # 1. Verify bundle HMAC signature if provided/configured
        if bundle_data is not None or effective_sig is not None:
            if effective_secret is None:
                msg = "Bundle secret is required for HMAC signature verification"
                raise InvalidSignatureError(msg)
            verify_bundle_signature(
                bundle_data=bundle_data,
                secret=effective_secret,
                expected_signature=effective_sig,
            )

        # 2. Merge environment variables and scan for production credentials
        combined_env: dict[str, str] = {}
        combined_env.update(self.config.mock_credentials)
        if env:
            combined_env.update(env)

        scan_credentials(env_vars=combined_env, content=bundle_data)

        # 3. Create sandbox container instance
        container_id = f"sbx_{uuid.uuid4().hex[:12]}"
        container = SandboxContainer(
            container_id=container_id,
            config=self.config,
            ledger=self.ledger,
            env=combined_env,
        )
        return container
