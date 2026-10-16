"""ARC Control Plane Warehouse.

Unites relational database stores (PostgreSQL / SQLite) with content-addressed
blob stores (S3 / MinIO) for CTF trace management, signed bundle generation,
and escaped bug tracking.

Classes:
    TraceWarehouse: Unified storage facade for saving, querying, and rehydrating traces.
    DatabaseStore: Relational store managing metadata, candidates, and rejected hashes.
    S3BlobStore: Content-addressed payload store hashing objects via SHA-256.
    HarnessBundleGenerator: Creates signed, truncated execution bundles for offline replay.
    BundleSignatureVerifier: Verifies HMAC-SHA256 signatures on Harness Bundles.
    EscapedBugTracker: Tracks escaped production incidents and quarterly bug rates.
"""

from __future__ import annotations

from arc.control_plane.warehouse.blob_store import S3BlobStore
from arc.control_plane.warehouse.bundle_generator import (
    BundleSignatureVerifier,
    HarnessBundleGenerator,
    InvalidBundleSignatureError,
    canonical_json_bytes,
)
from arc.control_plane.warehouse.db_store import DatabaseStore
from arc.control_plane.warehouse.escaped_bugs import (
    EscapedBugTracker,
    calculate_quarterly_escaped_bug_rate,
    tag_incident,
)
from arc.control_plane.warehouse.warehouse import TraceWarehouse

__all__ = [
    "BundleSignatureVerifier",
    "DatabaseStore",
    "EscapedBugTracker",
    "HarnessBundleGenerator",
    "InvalidBundleSignatureError",
    "S3BlobStore",
    "TraceWarehouse",
    "calculate_quarterly_escaped_bug_rate",
    "canonical_json_bytes",
    "tag_incident",
]
