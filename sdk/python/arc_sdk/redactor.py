"""Tier 1 Redactor / Sanitizer module for arc_sdk.

Quét và làm mờ các bí mật (API keys, tokens, high-entropy secrets)
ngay tại nguồn trước khi serialize ra mạng hoặc lưu vào Trace Warehouse.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RedactionRule:
    rule_id: str
    pattern: re.Pattern[str]
    placeholder: str

    @classmethod
    def create(cls, rule_id: str, regex_pattern: str) -> RedactionRule:
        return cls(
            rule_id=rule_id,
            pattern=re.compile(regex_pattern),
            placeholder=f"[REDACTED:{rule_id}]",
        )


DEFAULT_RULES: list[RedactionRule] = [
    RedactionRule.create("stripe_live_key", r"sk_live_[0-9a-zA-Z]{24,}"),
    RedactionRule.create("stripe_test_key", r"sk_test_[0-9a-zA-Z]{24,}"),
    RedactionRule.create("aws_key", r"AKIA[0-9A-Z]{16}"),
    RedactionRule.create("generic_bearer", r"Bearer\s+[A-Za-z0-9\-\._~\+\/]+=*"),
    RedactionRule.create(
        "jwt_token", r"eyJ[A-Za-z0-9-_=]+\.eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]*"
    ),
]


def calculate_shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    probabilities = [float(s.count(c)) / len(s) for c in set(s)]
    return -sum(p * math.log2(p) for p in probabilities)


class Redactor:
    """Tier 1 Redactor làm sạch payload dữ liệu trước khi ghi nhận trace."""

    def __init__(
        self,
        rules: list[RedactionRule] | None = None,
        enable_entropy_check: bool = False,
        entropy_threshold: float = 4.5,
        min_entropy_length: int = 20,
    ) -> None:
        self.rules: list[RedactionRule] = rules if rules is not None else DEFAULT_RULES
        self.enable_entropy_check: bool = enable_entropy_check
        self.entropy_threshold: float = entropy_threshold
        self.min_entropy_length: int = min_entropy_length

    def redact_text(self, text: str) -> str:
        """Quét và làm sạch một chuỗi văn bản."""
        if not text:
            return text

        result = text
        for rule in self.rules:
            result = rule.pattern.sub(rule.placeholder, result)

        if self.enable_entropy_check and len(result) >= self.min_entropy_length:
            # Check for high-entropy tokens if enabled
            tokens = result.split()
            new_tokens: list[str] = []
            for token in tokens:
                if (
                    len(token) >= self.min_entropy_length
                    and not token.startswith("[REDACTED:")
                    and calculate_shannon_entropy(token) >= self.entropy_threshold
                ):
                    new_tokens.append("[REDACTED:high_entropy_secret]")
                else:
                    new_tokens.append(token)
            result = " ".join(new_tokens)

        return result

    def redact(self, data: Any, seen: set[int] | None = None) -> Any:
        """Hàm đệ quy làm sạch bất kỳ cấu trúc dữ liệu nào (dict, list, str, tuple)."""
        if seen is None:
            seen = set()

        if isinstance(data, str):
            return self.redact_text(data)
        elif isinstance(data, (dict, list, tuple, set)):
            obj_id = id(data)
            if obj_id in seen:
                return "[CIRCULAR]"
            seen.add(obj_id)

            if isinstance(data, dict):
                return {
                    self.redact(k, seen): self.redact(v, seen)
                    for k, v in data.items()
                }
            elif isinstance(data, list):
                return [self.redact(item, seen) for item in data]
            elif isinstance(data, tuple):
                return tuple(self.redact(item, seen) for item in data)
            elif isinstance(data, set):
                return {self.redact(item, seen) for item in data}
        return data


_default_redactor = Redactor()


def redact_payload(data: Any) -> Any:
    """Utility function cho phép redact payload theo bộ luật mặc định."""
    return _default_redactor.redact(data)
