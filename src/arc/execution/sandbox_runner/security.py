"""Security scanner and HMAC signature verification for Sandbox Runner."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any


class SecurityViolationError(Exception):
    """Raised when security violations occur, such as production credentials detected."""


class InvalidSignatureError(SecurityViolationError):
    """Raised when bundle HMAC signature verification fails."""


PROD_CREDENTIAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Stripe Secret Key", re.compile(r"sk_live_[0-9a-zA-Z]{10,}")),
    ("Stripe Restricted Key", re.compile(r"rk_live_[0-9a-zA-Z]{10,}")),
    ("Stripe Publishable Key", re.compile(r"pk_live_[0-9a-zA-Z]{10,}")),
    ("AWS Access Key ID", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub Personal Access Token", re.compile(r"ghp_[a-zA-Z0-9]{36}")),
    ("GitHub Fine-Grained Token", re.compile(r"github_pat_[a-zA-Z0-9_]{22,}")),
    ("GitLab Personal Access Token", re.compile(r"glpat-[a-zA-Z0-9\-]{20}")),
    ("Slack Token", re.compile(r"xox[baprs]-[a-zA-Z0-9\-]+")),
    ("Generic Production Token", re.compile(r"(?i)(live_secret|prod_key|production_token)_[a-zA-Z0-9]{10,}")),
]


def scan_credentials(
    env_vars: dict[str, str] | None = None,
    content: Any = None,
) -> list[str]:
    """Scans environment variables and content for production credential patterns.

    Raises SecurityViolationError if any production credential is found.
    Returns list of detected violation names if no exception is raised.
    """
    violations: list[str] = []

    if env_vars:
        for k, v in env_vars.items():
            if not isinstance(v, str):
                continue
            for name, pattern in PROD_CREDENTIAL_PATTERNS:
                if pattern.search(v):
                    msg = f"Production credential pattern '{name}' detected in env var '{k}'"
                    raise SecurityViolationError(msg)

    if content is not None:
        text_content = json.dumps(content) if isinstance(content, (dict, list)) else str(content)
        for name, pattern in PROD_CREDENTIAL_PATTERNS:
            if pattern.search(text_content):
                msg = f"Production credential pattern '{name}' detected in content payload"
                raise SecurityViolationError(msg)

    return violations


def canonical_bytes(data: Any) -> bytes:
    """Serializes data into canonical JSON bytes."""
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode("utf-8")
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_hmac_signature(bundle_data: Any, secret: str | bytes) -> str:
    """Computes HMAC-SHA256 signature for bundle data using secret."""
    secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret
    payload = canonical_bytes(bundle_data)
    return hmac.new(secret_bytes, payload, hashlib.sha256).hexdigest()


def verify_bundle_signature(
    bundle_data: Any,
    secret: str | bytes,
    expected_signature: str | None = None,
) -> bool:
    """Verifies HMAC signature of bundle.

    If expected_signature is None, attempts to extract 'signature' field from bundle_data if it's a dict.
    Raises InvalidSignatureError if signature is invalid or missing when required.
    """
    if expected_signature is None:
        if isinstance(bundle_data, dict) and "signature" in bundle_data:
            expected_signature = str(bundle_data["signature"])
            bundle_to_sign = {k: v for k, v in bundle_data.items() if k != "signature"}
        else:
            msg = "No expected signature provided or found in bundle"
            raise InvalidSignatureError(msg)
    else:
        bundle_to_sign = bundle_data

    computed_sig = compute_hmac_signature(bundle_to_sign, secret)

    if not hmac.compare_digest(computed_sig, expected_signature):
        msg = f"Invalid HMAC signature: expected '{expected_signature}', computed '{computed_sig}'"
        raise InvalidSignatureError(msg)

    return True
