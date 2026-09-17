"""HarnessBundle Generator and HMAC-SHA256 Signer/Verifier.

Generates standalone, tamper-proof execution bundles for local replay and CI runners
according to §4.4 and schemas/json/bundle_v1.json.
"""

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any


class InvalidBundleSignatureError(ValueError):
    """Raised when bundle HMAC signature verification fails due to tampering or wrong key."""


def canonical_json_bytes(data: Any) -> bytes:
    """Serializes data structure into canonical, deterministic UTF-8 JSON bytes."""
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


class HarnessBundleGenerator:
    """Generates schema-compliant, signed HarnessBundle dictionaries from CTF v1.0 traces."""

    @classmethod
    def generate(
        cls,
        ctf_data: dict[str, Any],
        secret_key: str,
        key_id: str = "default",
        max_steps: int = 10000,
        window_size_around_fork: int = 50,
    ) -> dict[str, Any]:
        """Generates a signed HarnessBundle v1.0 payload from CTF v1.0 trace data.

        Applies window truncation (±50 steps around fork point) if steps exceed max_steps.
        Computes HMAC-SHA256 signature over the payload content.
        """
        source_trace_id = str(ctf_data.get("trace_id", "unknown"))
        agent_meta = ctf_data.get("agent")
        if isinstance(agent_meta, dict):
            target_service = agent_meta.get("name", "unknown")
        else:
            target_service = str(agent_meta or "unknown")

        steps = list(ctf_data.get("steps", []))
        effects = list(ctf_data.get("effects", []))

        # Truncation logic: if total steps exceed max_steps (e.g. 10,000), slice window around fork point
        if len(steps) > max_steps:
            fork_idx = None
            for idx, s in enumerate(steps):
                if s.get("forkable") or s.get("fork_reasons"):
                    fork_idx = idx
                    break

            if fork_idx is None:
                fork_idx = len(steps) // 2

            start_idx = max(0, fork_idx - window_size_around_fork)
            end_idx = min(len(steps), fork_idx + window_size_around_fork + 1)
            steps = steps[start_idx:end_idx]

            # Filter effects to match truncated steps
            step_ids = {s["step_id"] for s in steps}
            effects = [e for e in effects if e.get("step_id") in step_ids]

        # Extract cassettes from tool call steps
        cassettes: list[dict[str, Any]] = []
        for s in steps:
            req = s.get("request") or {}
            resp = s.get("response") or {}
            tool_name = req.get("tool")
            if tool_name:
                args_val = req.get("args_ref") or req.get("args") or {}
                if isinstance(args_val, str) and args_val.startswith("sha256:"):
                    req_hash = args_val
                else:
                    req_hash = f"sha256:{hashlib.sha256(canonical_json_bytes(args_val)).hexdigest()}"

                cassettes.append(
                    {
                        "tool": tool_name,
                        "request_hash": req_hash,
                        "response_body_ref": resp.get("body_ref"),
                        "status": resp.get("status", "ok"),
                    }
                )

        generated_at = datetime.now(timezone.utc).isoformat()
        determinism_level = ctf_data.get("determinism_level", "L2")
        if determinism_level not in ("L0", "L1", "L2", "L3"):
            determinism_level = "L2"

        entrypoint = {
            "agent": target_service,
            "version": agent_meta.get("version", "1.0.0") if isinstance(agent_meta, dict) else "1.0.0",
        }

        # Build payload bundle without signature
        bundle_unsigned: dict[str, Any] = {
            "bundle_id": f"bnd_{source_trace_id}",
            "bundle_schema_version": "1.0",
            "generated_at": generated_at,
            "source_trace_id": source_trace_id,
            "target_service": target_service,
            "determinism_level": determinism_level,
            "entrypoint": entrypoint,
            "steps": steps,
            "effects": effects,
            "cassettes": cassettes,
            "state_snapshots": ctf_data.get("final_state_ref") or ctf_data.get("state_snapshots"),
            "invariants_applied": ctf_data.get("invariants_applied", []),
        }

        # Compute HMAC-SHA256 signature
        sig_value = hmac.new(
            secret_key.encode("utf-8"),
            canonical_json_bytes(bundle_unsigned),
            hashlib.sha256,
        ).hexdigest()

        bundle = dict(bundle_unsigned)
        bundle["signature"] = {
            "alg": "HMAC-SHA256",
            "key_id": key_id,
            "value": sig_value,
        }

        return bundle


class BundleSignatureVerifier:
    """Verifies HMAC-SHA256 signatures for HarnessBundle payloads."""

    @classmethod
    def verify(cls, bundle: dict[str, Any], secret_key: str, raise_on_error: bool = True) -> bool:
        """Verifies the signature of a HarnessBundle dictionary.

        Returns True if signature is valid.
        If signature is invalid/tampered/missing and raise_on_error is True, raises InvalidBundleSignatureError.
        If raise_on_error is False, returns False on failure.
        """
        signature = bundle.get("signature")
        if not signature or not isinstance(signature, dict):
            if raise_on_error:
                raise InvalidBundleSignatureError("Bundle is missing required signature block")
            return False

        if signature.get("alg") != "HMAC-SHA256":
            if raise_on_error:
                raise InvalidBundleSignatureError(
                    f"Unsupported signature algorithm: {signature.get('alg')}"
                )
            return False

        sig_value = signature.get("value")
        if not sig_value:
            if raise_on_error:
                raise InvalidBundleSignatureError("Bundle signature value is missing")
            return False

        # Re-create payload dictionary excluding signature
        bundle_unsigned = {k: v for k, v in bundle.items() if k != "signature"}

        expected_sig = hmac.new(
            secret_key.encode("utf-8"),
            canonical_json_bytes(bundle_unsigned),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_sig, sig_value):
            if raise_on_error:
                raise InvalidBundleSignatureError(
                    "Invalid bundle signature: payload has been tampered or wrong key used"
                )
            return False

        return True
