"""ARC Isolated Sandbox Runner.

Provides zero-production network-isolated execution environments (Docker/UDS),
cassette player with 4-tier match strategy, and passive effect ledger trapping.

Classes:
    SandboxRunner: Manages sandbox container lifecycle, security verification, and replay.
    SandboxContainer: Running isolated container instance with egress prevention.
    SandboxConfig: Configuration settings for container networking and credentials.
    ReplayMode: Enum specifying cassette lookup and fault injection ordering.
    PassiveEffectLedger: In-memory ledger trapping mutating tool side-effects.
    CassettePlayer: Playback engine with exact hash, dynamic field masking, and fallback models.
    CassetteRecord: Recorded tool execution entry.
    CassetteMissException: Exception raised when tool replay misses across all strategies.
"""

from __future__ import annotations

from arc.execution.sandbox_runner.cassette_player import (
    CassetteMissException,
    CassettePlayer,
    CassetteRecord,
    compute_canonical_hash,
    mask_dynamic_fields,
)
from arc.execution.sandbox_runner.passive_ledger import (
    PassiveEffectLedger,
    is_mutating_tool,
)
from arc.execution.sandbox_runner.runner import (
    NetworkConfig,
    ReplayMode,
    SandboxConfig,
    SandboxContainer,
    SandboxRunner,
)
from arc.execution.sandbox_runner.security import (
    InvalidSignatureError,
    SecurityViolationError,
    compute_hmac_signature,
    scan_credentials,
    verify_bundle_signature,
)

__all__ = [
    "CassetteMissException",
    "CassettePlayer",
    "CassetteRecord",
    "InvalidSignatureError",
    "NetworkConfig",
    "PassiveEffectLedger",
    "ReplayMode",
    "SandboxConfig",
    "SandboxContainer",
    "SandboxRunner",
    "SecurityViolationError",
    "compute_canonical_hash",
    "compute_hmac_signature",
    "is_mutating_tool",
    "mask_dynamic_fields",
    "scan_credentials",
    "verify_bundle_signature",
]
