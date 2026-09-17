"""Cassette Engine and Rule-based Masking Matcher for Deterministic Replay.

Provides CassettePlayer for recording and playing back tool execution responses
isolated from external networks, utilizing a 4-tier match strategy:
1. Canonical Exact Hash Match (SHA-256)
2. Rule-based Masking Matcher (JSON path dynamic field stripping)
3. Tool Model Fallback
4. Transparent Abort (CassetteMissException) with metric tracking.
"""

import hashlib
import json
from collections.abc import Callable
from typing import Any


class CassetteMissException(Exception):
    """Raised when a cassette lookup fails across all matching strategies and no tool model fallback exists."""

    def __init__(self, tool_name: str, args: dict[str, Any], message: str | None = None) -> None:
        self.tool_name = tool_name
        self.request_args = args
        self.tool_args = args
        msg = message or f"Cassette miss for tool '{tool_name}' with args {args}"
        super().__init__(msg)


DEFAULT_DYNAMIC_FIELDS: set[str] = {
    "timestamp",
    "nonce",
    "request_id",
    "client_trace_id",
    "session_token",
}


def canonical_json_bytes(data: Any) -> bytes:
    """Serializes data structure into canonical, deterministic UTF-8 JSON bytes."""
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_canonical_hash(args: Any) -> str:
    """Computes SHA-256 hash string for canonical JSON representation of arguments."""
    return hashlib.sha256(canonical_json_bytes(args)).hexdigest()


def mask_dynamic_fields(
    data: Any, dynamic_fields: set[str] | None = None
) -> Any:
    """Recursively strips pre-configured dynamic fields from a data structure (dict/list)."""
    fields_to_mask = dynamic_fields if dynamic_fields is not None else DEFAULT_DYNAMIC_FIELDS

    if isinstance(data, dict):
        result: dict[str, Any] = {}
        for k, v in data.items():
            if k in fields_to_mask:
                continue
            result[k] = mask_dynamic_fields(v, fields_to_mask)
        return result
    if isinstance(data, list):
        return [mask_dynamic_fields(item, fields_to_mask) for item in data]
    return data


class CassetteRecord:
    """Represents a single recorded cassette entry for a tool call."""

    def __init__(
        self,
        tool: str,
        request_args: dict[str, Any] | None = None,
        request_hash: str | None = None,
        response: dict[str, Any] | None = None,
        status: str = "ok",
    ) -> None:
        self.tool = tool
        self.request_args = request_args
        if request_hash:
            clean_hash = request_hash.removeprefix("sha256:")
            self.request_hash = clean_hash
        elif request_args is not None:
            self.request_hash = compute_canonical_hash(request_args)
        else:
            self.request_hash = ""
        self.response = response if response is not None else {"status": status}
        self.status = status

    def to_dict(self) -> dict[str, Any]:
        """Serializes record to standard dictionary format."""
        return {
            "tool": self.tool,
            "request_hash": f"sha256:{self.request_hash}",
            "request_args": self.request_args,
            "response": self.response,
            "status": self.status,
        }


ToolModelCallable = Callable[[str, dict[str, Any]], dict[str, Any]]


class CassettePlayer:
    """Cassette Player engine for tool execution playback and matching."""

    def __init__(
        self,
        records: list[CassetteRecord | dict[str, Any]] | None = None,
        dynamic_fields: set[str] | None = None,
        tool_models: dict[str, ToolModelCallable] | None = None,
    ) -> None:
        self.records: list[CassetteRecord] = []
        if records:
            for r in records:
                self.add_record(r)

        self.dynamic_fields: set[str] = (
            set(dynamic_fields) if dynamic_fields is not None else set(DEFAULT_DYNAMIC_FIELDS)
        )
        self.tool_models: dict[str, ToolModelCallable] = (
            dict(tool_models) if tool_models is not None else {}
        )

        self.total_requests: int = 0
        self.miss_count: int = 0
        self.exact_matches: int = 0
        self.rule_matches: int = 0
        self.tool_model_fallback_matches: int = 0

    @property
    def cassette_miss_rate(self) -> float:
        """Returns the cassette miss rate as a float between 0.0 and 1.0."""
        if self.total_requests == 0:
            return 0.0
        return self.miss_count / self.total_requests

    def add_record(self, record: CassetteRecord | dict[str, Any]) -> None:
        """Appends a new cassette record."""
        if isinstance(record, CassetteRecord):
            self.records.append(record)
        elif isinstance(record, dict):
            tool_name = str(record.get("tool", ""))
            req_args = record.get("request_args")
            if req_args is None and "args" in record:
                req_args = record.get("args")
            req_hash = record.get("request_hash")
            resp = record.get("response")
            if resp is None and "response_body" in record:
                resp = record.get("response_body")
            if resp is None and "response_body_ref" in record:
                resp = record.get("response_body_ref")
            if resp is None:
                resp = {"status": record.get("status", "ok")}
            elif not isinstance(resp, dict):
                resp = {"data": resp, "status": record.get("status", "ok")}

            st = str(record.get("status", "ok"))
            self.records.append(
                CassetteRecord(
                    tool=tool_name,
                    request_args=req_args if isinstance(req_args, dict) else None,
                    request_hash=str(req_hash) if req_hash else None,
                    response=resp if isinstance(resp, dict) else {"data": resp},
                    status=st,
                )
            )

    def register_tool_model(self, tool_name: str, model_fn: ToolModelCallable) -> None:
        """Registers a fallback tool model simulator function for a specific tool."""
        self.tool_models[tool_name] = model_fn

    def replay(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Executes replay request for a tool call using 4 matching strategies in priority order.

        Strategy 1: Canonical Exact Hash Match
        Strategy 2: Rule-based Masking Matcher
        Strategy 3: Tool Model Fallback
        Strategy 4: Transparent Abort (raises CassetteMissException)
        """
        self.total_requests += 1

        # Strategy 1: Canonical Exact Hash Match
        req_hash = compute_canonical_hash(args)
        for rec in self.records:
            if rec.tool == tool_name and rec.request_hash == req_hash:
                self.exact_matches += 1
                return rec.response

        # Strategy 2: Rule-based Masking Matcher
        masked_req_args = mask_dynamic_fields(args, self.dynamic_fields)
        for rec in self.records:
            if rec.tool == tool_name and rec.request_args is not None:
                masked_rec_args = mask_dynamic_fields(rec.request_args, self.dynamic_fields)
                if masked_req_args == masked_rec_args:
                    self.rule_matches += 1
                    return rec.response

        # Strategy 3: Tool Model Fallback
        if tool_name in self.tool_models:
            self.tool_model_fallback_matches += 1
            model_fn = self.tool_models[tool_name]
            return model_fn(tool_name, args)

        # Strategy 4: Transparent Abort
        self.miss_count += 1
        raise CassetteMissException(tool_name=tool_name, args=args)
