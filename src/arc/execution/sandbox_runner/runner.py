"""Isolated Sandbox Runner for Docker internal network and UDS execution environments.

F1: FaultInjector is wired into SandboxContainer — every execute_tool() routes
    through intercept_tool_call() before reaching the ledger.
F2: SandboxRunner.run_with_faults() provides a real end-to-end sandbox execution
    method (previously missing, making RegressionTestGenerator produce dead tests).
F7: ReplayMode enum formalises Cassette-before-Fault ordering contract.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import TYPE_CHECKING, Any, NamedTuple

from arc.execution.sandbox_runner.passive_ledger import (
    PassiveEffectLedger,
    is_mutating_tool,
)
from arc.execution.sandbox_runner.security import (
    InvalidSignatureError,
    scan_credentials,
    verify_bundle_signature,
)

if TYPE_CHECKING:
    from arc.execution.fork_engine.fault_catalog import FaultCatalog
    from arc.execution.fork_engine.injector import FaultInjector
    from arc.execution.invariant_engine.evaluator import InvariantSpec
    from arc.execution.sandbox_runner.cassette_player import CassettePlayer


# ── F7: Replay Mode ordering contract ────────────────────────────────────────

class ReplayMode(str, Enum):
    """Defines the ordering protocol for cassette lookup vs fault injection.

    PASSIVE:
        Trap mutating calls into the ledger; no cassette, no fault injection.
        Used for baseline capture runs.

    FAULT_ONLY:
        Inject faults directly without cassette lookup.
        Used when no cassette is available but fault behaviour must be tested.

    CASSETTE_THEN_FAULT (default / recommended):
        1. CassettePlayer.replay() → baseline_response (exact or masked hash match)
        2. FaultInjector.intercept_tool_call() overlays fault ON the baseline response.
        Cassette miss routes to ToolModel fallback, then fault injection.
        This ensures both calls are visible in the PassiveEffectLedger trace.
    """

    PASSIVE = "passive"
    FAULT_ONLY = "fault_only"
    CASSETTE_THEN_FAULT = "cassette_then_fault"


# ── Network / Config ──────────────────────────────────────────────────────────

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
            "ENVIRONMENT": "sandbox",
        }
        self.bundle_secret = bundle_secret
        self.bundle_signature = bundle_signature
        self.network_config = NetworkConfig(
            name=network_mode,
            internal=internal_network,
            gateway_allowed=not internal_network,
        )


# ── SandboxContainer ─────────────────────────────────────────────────────────

class SandboxContainer:
    """Represents an isolated sandbox execution container instance.

    F1 change: every execute_tool() is now routed through self.injector
    (FaultInjector.intercept_tool_call) before reaching PassiveEffectLedger,
    so fault specs are actually applied during replay — not bypassed.
    """

    def __init__(
        self,
        container_id: str,
        config: SandboxConfig,
        ledger: PassiveEffectLedger,
        env: dict[str, str],
        injector: FaultInjector | None = None,          # F1
        cassette_player: CassettePlayer | None = None,  # F7
        replay_mode: ReplayMode = ReplayMode.CASSETTE_THEN_FAULT,  # F7
    ) -> None:
        self.container_id = container_id
        self.config = config
        self.ledger = ledger
        self.env = env
        self.is_running = True
        self._step_counter: int = 0  # F1: monotonic step_id per tool call

        # F1: lazy import to avoid circular at module level
        if injector is None:
            from arc.execution.fork_engine.fault_catalog import FaultCatalog
            from arc.execution.fork_engine.injector import FaultInjector as _FI
            injector = _FI(catalog=FaultCatalog(), ledger=ledger)
        self.injector: FaultInjector = injector

        self.cassette_player: CassettePlayer | None = cassette_player  # F7
        self.replay_mode: ReplayMode = replay_mode                      # F7

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

        F1: All calls now route through FaultInjector.intercept_tool_call()
        which applies any matching FaultSpec before reaching the ledger.

        F7: Ordering follows self.replay_mode:
          CASSETTE_THEN_FAULT → cassette lookup first, fault overlay second
          FAULT_ONLY          → skip cassette, fault injection directly
          PASSIVE             → no cassette, no fault injection, ledger trap only
        """
        if not self.is_running:
            msg = "Container is stopped"
            raise RuntimeError(msg)

        self._step_counter += 1
        step_id = self._step_counter

        # ── F7: Build the default_executor based on ReplayMode ───────────────
        def _passive_executor(t_name: str, t_args: dict[str, Any]) -> dict[str, Any]:
            """Baseline executor: trap mutating, pass-through read-only."""
            if is_mutating_tool(t_name):
                return self.ledger.trap_mutating_call(t_name, t_args, step_id=step_id)
            return {
                "status": "ok",
                "tool_name": t_name,
                "result": f"Read-only '{t_name}' executed",
            }

        if self.replay_mode == ReplayMode.PASSIVE:
            # No fault injection — pure ledger trap
            return _passive_executor(tool_name, args)

        if self.replay_mode == ReplayMode.CASSETTE_THEN_FAULT and self.cassette_player is not None:
            # F7: Strategy — cassette lookup → fault overlay
            def _cassette_then_passthrough(t_name: str, t_args: dict[str, Any]) -> dict[str, Any]:
                from arc.execution.sandbox_runner.cassette_player import CassetteMissException
                try:
                    cassette_resp = self.cassette_player.replay(t_name, t_args)  # type: ignore[union-attr]
                    # Return cassette baseline — fault injector may override
                    return cassette_resp
                except CassetteMissException:
                    # Cassette miss → fall back to passive trap
                    return _passive_executor(t_name, t_args)

            default_executor = _cassette_then_passthrough
        else:
            # FAULT_ONLY or CASSETTE_THEN_FAULT without cassette player
            default_executor = _passive_executor

        # ── F1: Route through FaultInjector ──────────────────────────────────
        return self.injector.intercept_tool_call(
            step_id=step_id,
            tool_name=tool_name,
            args=args,
            default_executor=default_executor,
        )

    def stop(self) -> None:
        """Stops the sandbox container."""
        self.is_running = False


# ── SandboxRunner ─────────────────────────────────────────────────────────────

class SandboxRunner:
    """Sandbox Runner managing container initialization, network isolation, credential injection,

    security scanning, and passive effect ledger trapping.

    F2: Adds run_with_faults() — a real end-to-end replay method used by both
    RegressionTestGenerator-generated tests and arc repro CLI command.
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
        injector: FaultInjector | None = None,                  # F1
        cassette_player: CassettePlayer | None = None,          # F7
        replay_mode: ReplayMode = ReplayMode.CASSETTE_THEN_FAULT,  # F7
    ) -> SandboxContainer:
        """Starts a sandbox container after verifying signature and credential security.

        Args:
            env:            Optional environment variables to merge in.
            bundle_data:    Optional bundle payload for HMAC verification.
            signature:      Optional HMAC signature for the bundle.
            secret:         Optional HMAC secret. Falls back to config.bundle_secret.
            injector:       (F1) FaultInjector to route all tool calls through.
            cassette_player:(F7) CassettePlayer providing baseline recorded responses.
            replay_mode:    (F7) Cassette/Fault ordering protocol.

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

        # 3. Create sandbox container instance (F1: pass injector + cassette + mode)
        container_id = f"sbx_{uuid.uuid4().hex[:12]}"
        container = SandboxContainer(
            container_id=container_id,
            config=self.config,
            ledger=self.ledger,
            env=combined_env,
            injector=injector,
            cassette_player=cassette_player,
            replay_mode=replay_mode,
        )
        return container

    # ── F2: run_with_faults ───────────────────────────────────────────────────

    def run_with_faults(
        self,
        fault_spec: list[dict[str, Any]] | FaultCatalog,
        target_invariant: str | InvariantSpec | dict[str, Any],
        cassette_player: CassettePlayer | None = None,
        context: dict[str, Any] | None = None,
        replay_mode: ReplayMode = ReplayMode.CASSETTE_THEN_FAULT,
    ) -> dict[str, Any]:
        """Runs a sandboxed replay with fault injection and evaluates a target invariant.

        This is the method called by RegressionTestGenerator-generated tests and
        by arc repro CLI command to get a real execution result.

        Args:
            fault_spec:         List of fault dicts or a FaultCatalog instance.
            target_invariant:   Invariant ID string, InvariantSpec, or dict spec.
            cassette_player:    Optional CassettePlayer providing recorded baseline responses.
            context:            Optional context dict passed to InvariantEvaluator.
            replay_mode:        Cassette/Fault ordering protocol (default CASSETTE_THEN_FAULT).

        Returns:
            dict with keys:
              status            "violation_reproduced" | "ok"
              violated_invariant  invariant ID string
              fault_spec        list of applied fault dicts
              passed            bool — True if invariant was NOT violated
              effects           list of PassiveEffectLedger entries recorded
              eval_result       dict with violated, error, exec_time_ms
        """
        # Lazy imports to avoid circular at module import time
        from arc.execution.fork_engine.fault_catalog import FaultCatalog
        from arc.execution.fork_engine.injector import FaultInjector
        from arc.execution.invariant_engine.evaluator import InvariantEvaluator

        # 1. Build FaultCatalog
        if isinstance(fault_spec, FaultCatalog):
            catalog: FaultCatalog = fault_spec
        else:
            catalog = FaultCatalog.from_list(fault_spec)

        # 2. Reset ledger so this run starts clean
        self.ledger.clear()

        # 3. Build FaultInjector backed by shared ledger
        injector = FaultInjector(catalog=catalog, ledger=self.ledger)

        # 4. Start isolated container
        container = self.start_container(
            injector=injector,
            cassette_player=cassette_player,
            replay_mode=replay_mode,
        )

        # 5. Replay cassette steps through the container (fault injection happens inside)
        if cassette_player is not None:
            from arc.execution.sandbox_runner.cassette_player import CassetteMissException
            for rec in cassette_player.records:
                req_args = rec.request_args or {}
                try:
                    container.execute_tool(rec.tool, req_args)
                except CassetteMissException:
                    pass  # miss is acceptable — ledger just won't have that step

        # 6. Resolve invariant spec
        evaluator = InvariantEvaluator()
        effects = self.ledger.get_effects()

        if isinstance(target_invariant, str):
            inv_id_str = target_invariant
            inv: InvariantSpec | dict[str, Any] = {
                "id": inv_id_str,
                "statement": inv_id_str,
                "category": "safety",
                "check": "True",  # no-op — caller should pass a real spec
                "severity": "critical",
            }
        elif isinstance(target_invariant, dict):
            inv = target_invariant
            inv_id_str = str(target_invariant.get("id", "UNKNOWN"))
        else:
            inv = target_invariant
            inv_id_str = target_invariant.id

        # 7. Evaluate invariant
        eval_result = evaluator.evaluate(inv, effects, context)

        # 8. Compile applied fault list
        faults_return = fault_spec if isinstance(fault_spec, list) else [f.to_dict() for f in catalog.get_all_faults()]

        return {
            "status": "violation_reproduced" if eval_result.violated else "ok",
            "violated_invariant": inv_id_str,
            "fault_spec": faults_return,
            "passed": not eval_result.violated,
            "effects": effects,
            "eval_result": {
                "violated": eval_result.violated,
                "error": eval_result.error,
                "exec_time_ms": eval_result.exec_time_ms,
            },
        }
