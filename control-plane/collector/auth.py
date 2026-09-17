"""Authentication dependency for Collector REST API."""

import os

from fastapi import Header, HTTPException, status


def verify_token(authorization: str | None = Header(None)) -> str:
    """Verifies Bearer token against ARC_API_TOKEN_SECRET environment variable."""
    expected_token = os.getenv("ARC_API_TOKEN_SECRET", "valid_token")

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    token = parts[1]
    if token != expected_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    return token
