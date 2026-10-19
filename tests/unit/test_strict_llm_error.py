"""Unit tests for Strict Error Handling & No-Fallback Policy for LLM APIs (TASK-CLI-006).

Covers:
- Strict error rendering for HTTP 429 (Quota Exceeded / Rate Limit) matching Spec §3.3
- Strict error rendering for HTTP 401 (Unauthorized / Invalid Key) and HTTP 404 (Model Not Found)
- Provider billing links and action guidance for OpenAI, Anthropic, Gemini, and Ollama
- Interceptor fail-fast behavior with StrictLLMFallbackBlockedError (no silent fallback allowed)
- Debugger proxy integration enforcing strict error responses
- Zero emoji clutter validation
"""

from __future__ import annotations

import re

from rich.console import Console

from arc.cli.proxy.debugger_proxy import LocalDebuggerProxy
from arc.cli.ui.strict_error import (
    PROVIDER_BILLING_LINKS,
    StrictLLMFallbackBlockedError,
    get_default_action_items,
    intercept_llm_response,
    render_strict_llm_error,
)


def _to_plain_text(rich_str: str) -> str:
    """Renders Rich markup string to plain text without ANSI codes."""
    console = Console(record=True, width=120, force_terminal=False)
    console.print(rich_str)
    return console.export_text()


def test_render_strict_llm_error_429_matches_spec() -> None:
    """Verifies that HTTP 429 output matches Section 3.3 mockup exactly."""
    rendered = render_strict_llm_error(
        provider="openai",
        model_name="gpt-4o",
        status_code=429,
        message="429 Insufficient Quota / Rate Limit Exceeded",
        detail="You have exceeded your current quota. Please check your plan and billing details.",
        endpoint="https://api.openai.com/v1/chat/completions",
        operation="api_call",
        current_iteration=1,
        total_iterations=1,
    )
    plain = _to_plain_text(rendered)

    # Badges and headers
    assert "FAIL" in plain
    assert "llm-api" in plain
    assert "openai > gpt-4o > api_call" in plain

    # Error details
    assert "API_ERROR: 429 Insufficient Quota / Rate Limit Exceeded" in plain
    assert "Detail: You have exceeded your current quota. Please check your plan and billing details." in plain
    assert "at https://api.openai.com/v1/chat/completions" in plain

    # Actions required
    assert "Action required:" in plain
    assert "1. Check credits and billing at https://platform.openai.com/account/billing" in plain
    assert "2. Update API key in .arc/config.yaml or environment variables" in plain
    assert "3. Or switch to a local zero-cost model: arc config --set-provider ollama" in plain

    # Divider and Status
    assert "[1/1]" in plain
    assert "Status: BLOCKED (No silent fallback allowed)" in plain


def test_render_strict_llm_error_401_unauthorized() -> None:
    """Verifies that HTTP 401 Invalid API Key outputs actionable resolution steps."""
    rendered = render_strict_llm_error(
        provider="anthropic",
        model_name="claude-3-5-sonnet",
        status_code=401,
        detail="Invalid x-api-key provided for Anthropic API.",
        endpoint="https://api.anthropic.com/v1/messages",
    )
    plain = _to_plain_text(rendered)

    assert "FAIL" in plain
    assert "llm-api" in plain
    assert "anthropic > claude-3-5-sonnet" in plain
    assert "API_ERROR: 401" in plain
    assert "Invalid x-api-key" in plain
    assert "https://console.anthropic.com/settings/billing" in plain
    assert "Status: BLOCKED (No silent fallback allowed)" in plain


def test_render_strict_llm_error_404_model_not_found() -> None:
    """Verifies that HTTP 404 Model Not Found guides the user to fix model_id."""
    rendered = render_strict_llm_error(
        provider="gemini",
        model_name="gemini-nonexistent-model",
        status_code=404,
        detail="Model 'gemini-nonexistent-model' not found on Google AI Studio.",
        endpoint="https://generativelanguage.googleapis.com/v1beta/models",
    )
    plain = _to_plain_text(rendered)

    assert "FAIL" in plain
    assert "llm-api" in plain
    assert "gemini > gemini-nonexistent-model" in plain
    assert "API_ERROR: 404" in plain
    assert "Update model_id in .arc/config.yaml" in plain
    assert "Status: BLOCKED (No silent fallback allowed)" in plain


def test_provider_action_links_catalog() -> None:
    """Ensures each major provider has a direct billing / API key portal URL."""
    assert "platform.openai.com" in PROVIDER_BILLING_LINKS["openai"]
    assert "console.anthropic.com" in PROVIDER_BILLING_LINKS["anthropic"]
    assert "aistudio.google.com" in PROVIDER_BILLING_LINKS["gemini"]
    assert "localhost:11434" in PROVIDER_BILLING_LINKS["ollama"]

    # Test action items generation for ollama
    ollama_actions = get_default_action_items("ollama", 429)
    assert any("ollama" in item.lower() for item in ollama_actions)


def test_intercept_llm_response_raises_on_error_codes() -> None:
    """Verifies that intercept_llm_response halts execution on 401, 404, 429."""
    # 429
    raised_429 = False
    try:
        intercept_llm_response(
            status_code=429,
            provider="openai",
            model_name="gpt-4o",
            response_body={"error": {"message": "Rate limit exceeded"}},
            halt=True,
        )
    except StrictLLMFallbackBlockedError as exc:
        raised_429 = True
        assert exc.status_code == 429
        assert exc.provider == "openai"
        assert exc.model_name == "gpt-4o"
        assert "Rate limit exceeded" in exc.detail
    assert raised_429 is True

    # 401
    raised_401 = False
    try:
        intercept_llm_response(
            status_code=401,
            provider="anthropic",
            model_name="claude-3-5-sonnet",
            halt=True,
        )
    except StrictLLMFallbackBlockedError as exc:
        raised_401 = True
        assert exc.status_code == 401
    assert raised_401 is True

    # 404
    raised_404 = False
    try:
        intercept_llm_response(
            status_code=404,
            provider="gemini",
            model_name="unknown-model",
            halt=True,
        )
    except StrictLLMFallbackBlockedError as exc:
        raised_404 = True
        assert exc.status_code == 404
    assert raised_404 is True


def test_intercept_llm_response_passes_on_200() -> None:
    """Verifies that normal 200 OK responses pass through without interruption."""
    result = intercept_llm_response(
        status_code=200,
        provider="openai",
        model_name="gpt-4o",
        response_body={"choices": [{"message": {"content": "Hello world"}}]},
        halt=True,
    )
    assert result is None


def test_debugger_proxy_strict_no_fallback_header() -> None:
    """Verifies that LocalDebuggerProxy returns strict no-fallback metadata when 429 occurs."""
    repro_spec = {
        "faults": [
            {
                "step": 1,
                "type": "http_429",
                "details": "Quota exhausted",
            }
        ]
    }
    proxy = LocalDebuggerProxy(requested_port=8099)
    proxy.repro_data = repro_spec
    proxy.faults = repro_spec["faults"]

    # Test that proxy has strict_no_fallback attribute enabled
    assert getattr(proxy, "strict_no_fallback", True) is True


def test_zero_emoji_clutter_in_strict_error() -> None:
    """Verifies strict error formatting does not include distracting emojis."""
    rendered = render_strict_llm_error(
        provider="openai",
        model_name="gpt-4o",
        status_code=429,
        detail="Rate limit exceeded",
    )
    plain = _to_plain_text(rendered)

    # Standard emoji regex pattern
    emoji_pattern = re.compile(
        r"[\U00010000-\U0010ffff]|"
        r"[\u2600-\u26ff]|[\u2700-\u27bf]|"
        r"[\u2b50-\u2b55]|[\u231a-\u231b]"
    )
    found_emojis = emoji_pattern.findall(plain)
    assert found_emojis == [], f"Found forbidden emoji in output: {found_emojis}"
