"""S3 Content-Addressed Blob Storage for payloads (args, body, state snapshots).

Computes SHA-256 hash for content and stores blobs.
"""

import hashlib
import json
import os
from typing import Any


class S3BlobStore:
    """Content-Addressed Store using SHA-256 digest references."""

    def __init__(self, bucket_name: str | None = None, storage_dir: str | None = None) -> None:
        self.bucket_name = bucket_name or os.getenv("S3_BUCKET_NAME", "arc-traces")
        self.storage_dir = storage_dir or os.getenv("S3_LOCAL_STORAGE_DIR")
        self._in_memory_store: dict[str, bytes] = {}

    def _hash_bytes(self, content_bytes: bytes) -> str:
        digest = hashlib.sha256(content_bytes).hexdigest()
        return f"sha256:{digest}"

    def put(self, content: Any) -> str:
        """Serializes content, hashes with SHA-256, stores, and returns the reference string."""
        if content is None:
            return ""

        if isinstance(content, bytes):
            data_bytes = content
        elif isinstance(content, str):
            data_bytes = content.encode("utf-8")
        else:
            # Canonical JSON serialization
            data_bytes = json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")

        ref = self._hash_bytes(data_bytes)
        digest = ref.split(":", 1)[1]

        # Store in memory cache/store
        self._in_memory_store[digest] = data_bytes

        # If local storage dir specified, save to disk
        if self.storage_dir:
            os.makedirs(self.storage_dir, exist_ok=True)
            file_path = os.path.join(self.storage_dir, digest)
            with open(file_path, "wb") as f:
                f.write(data_bytes)

        return ref

    def get(self, ref: str) -> Any | None:
        """Retrieves content by sha256 reference. Returns deserialized JSON or raw str/bytes."""
        if not ref:
            return None

        digest = ref.split(":", 1)[-1] if ":" in ref else ref

        data_bytes: bytes | None = None
        if digest in self._in_memory_store:
            data_bytes = self._in_memory_store[digest]
        elif self.storage_dir:
            file_path = os.path.join(self.storage_dir, digest)
            if os.path.exists(file_path):
                with open(file_path, "rb") as f:
                    data_bytes = f.read()

        if data_bytes is None:
            return None

        try:
            return json.loads(data_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            try:
                return data_bytes.decode("utf-8")
            except UnicodeDecodeError:
                return data_bytes
