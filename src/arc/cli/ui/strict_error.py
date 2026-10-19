"""Strict Error Handling and No-Fallback Policy Engine (TASK-CLI-006).

Enforces the Strict No-Fallback Policy:
- Halts execution immediately on HTTP 401, 404, or 429 from LLM API providers.
- Prohibits silent model switching, automatic fallback, or swallowing API quota failures.
- Renders high-contrast, Playwright/Tester-Army style failure blocks with actionable resolution links.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console

from arc.cli.ui.badges import Badge

PROVIDER_BILLING_LINKS: dict[str, str] = {
    "openai": "https://platform.openai.com/account/billing",
    "anthropic": "https://console.anthropic.com/settings/billing",
    "gemini": "https://aistudio.google.com/app/apikey",
    "google": "https://aistudio.google.com/app/apikey",
    "ollama": "http://localhost:11434",
}

PROVIDER_ENDPOINTS: dict[str, str] = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models",
    "ollama": "http://localhost:11434/api/chat",
}


class StrictLLMFallbackBlockedError(Exception):
    """Raised when an LLM call fails with 401, 404, or 429 and silent fallback is blocked."""

    def __init__(
        self,
        provider: str,
        model_name: str,
        status_code: int,
        message: str = "",
        detail: str = "",
        endpoint: str = "",
        action_items: list[str] | None = None,
    ) -> None:
        self.provider = provider
        self.model_name = model_name
        self.status_code = status_code
        self.message = message or f"HTTP {status_code} Error"
        self.detail = detail
        self.endpoint = endpoint
        self.action_items = action_items or get_default_action_items(provider, status_code)
        super().__init__(
            f"[{provider}/{model_name}] {status_code} {self.message}: {self.detail}"
        )


def get_default_action_items(provider: str, status_code: int) -> list[str]:
    """Generates 3 actionable steps tailored to provider and HTTP status code."""
    prov_key = provider.lower()
    billing_link = PROVIDER_BILLING_LINKS.get(
        prov_key, f"https://platform.{prov_key}.com/account/billing"
    )

    if status_code == 429:
        if prov_key == "ollama":
            return [
                "1. Check local Ollama server status: curl http://localhost:11434/api/tags",
                "2. Ensure sufficient GPU VRAM or free system memory for model context",
                "3. Or reduce concurrency / request batch size in .arc/config.yaml",
            ]
        return [
            f"1. Check credits and billing at {billing_link}",
            "2. Update API key in .arc/config.yaml or environment variables",
            "3. Or switch to a local zero-cost model: arc config --set-provider ollama",
        ]

    if status_code == 401:
        return [
            f"1. Verify valid API key at {billing_link}",
            "2. Update API key in .arc/config.yaml or environment variables",
            "3. Or switch to a local zero-cost model: arc config --set-provider ollama",
        ]

    if status_code == 404:
        return [
            f"1. Check if model name exists on {provider} documentation/catalog",
            "2. Update model_id in .arc/config.yaml",
            "3. Or switch to standard verified model (e.g. gpt-4o, claude-3-5-sonnet, gemini-3.5-flash-lite)",
        ]

    return [
        f"1. Review provider documentation and service status at {billing_link}",
        "2. Verify endpoint configuration in .arc/config.yaml",
        "3. Or switch to a local zero-cost model: arc config --set-provider ollama",
    ]


def render_strict_llm_error(
    provider: str,
    model_name: str,
    status_code: int,
    message: str | None = None,
    detail: str | None = None,
    endpoint: str | None = None,
    action_items: list[str] | None = None,
    operation: str = "api_call",
    current_iteration: int = 1,
    total_iterations: int = 1,
    line_width: int = 100,
) -> str:
    """Renders high-contrast failure block strictly matching Section 3.3 mockup."""
    fail_badge = Badge.fail()
    llm_api_badge = Badge.llm_api()

    # Determine message title
    if message:
        message_clean = message.replace(f"{status_code}", "").strip()
        msg_title = f"{status_code} {message_clean}".strip()
    elif status_code == 429:
        msg_title = "429 Insufficient Quota / Rate Limit Exceeded"
    elif status_code == 401:
        msg_title = "401 Unauthorized / Invalid API Key"
    elif status_code == 404:
        msg_title = "404 Model Not Found / Invalid Resource"
    else:
        msg_title = f"{status_code} API Error"

    # Determine detail
    if not detail:
        if status_code == 429:
            detail = (
                "You have exceeded your current quota. Please check your plan and billing details."
            )
        elif status_code == 401:
            detail = f"Invalid API credentials provided for provider '{provider}'."
        elif status_code == 404:
            detail = f"Requested model '{model_name}' was not found on provider '{provider}'."
        else:
            detail = f"HTTP {status_code} returned by {provider} API."

    # Determine endpoint
    if not endpoint:
        endpoint = PROVIDER_ENDPOINTS.get(
            provider.lower(),
            f"https://api.{provider.lower()}.com/v1/chat/completions",
        )

    # Determine action items
    if not action_items:
        action_items = get_default_action_items(provider, status_code)

    # Separator divider
    sep_badge = f"[{current_iteration}/{total_iterations}]"
    dash_count = max(5, (line_width - len(sep_badge) - 2) // 2)
    separator = f"[dim]{'-' * dash_count} {sep_badge} {'-' * dash_count}[/dim]"

    parts: list[str] = [
        f" {fail_badge}   {llm_api_badge}  [bold]{provider}[/bold] > [dim]{model_name}[/dim] > [dim]{operation}[/dim]",
        f"[bold red]API_ERROR:[/bold red] {msg_title}",
        f" [cyan]> Detail:[/cyan] {detail}",
        f" [cyan]> at[/cyan] {endpoint}",
        " [cyan]> Action required:[/cyan]",
    ]

    for item in action_items:
        parts.append(f"   {item}")

    parts.extend([
        "",
        separator,
        "",
        "[bold red]Status: BLOCKED (No silent fallback allowed)[/bold red]",
    ])

    return "\n".join(parts)


def intercept_llm_response(
    status_code: int,
    provider: str = "openai",
    model_name: str = "gpt-4o",
    response_body: dict[str, Any] | str | None = None,
    endpoint: str | None = None,
    operation: str = "api_call",
    console: Console | None = None,
    halt: bool = True,
) -> str | None:
    """Intercepts an LLM API response; halts and renders strict error if error code is met.

    Only HTTP 401, 404, and 429 trigger the Strict No-Fallback blocker.
    """
    if status_code not in (401, 404, 429):
        return None

    detail = ""
    message = ""
    if isinstance(response_body, dict):
        err = response_body.get("error")
        if isinstance(err, dict):
            detail = str(err.get("message") or err.get("detail") or "")
            message = str(err.get("type") or "")
        elif isinstance(err, str):
            detail = err
        elif "detail" in response_body:
            detail = str(response_body["detail"])
        elif "message" in response_body:
            detail = str(response_body["message"])
    elif isinstance(response_body, str):
        detail = response_body

    rendered = render_strict_llm_error(
        provider=provider,
        model_name=model_name,
        status_code=status_code,
        message=message or None,
        detail=detail or None,
        endpoint=endpoint,
        operation=operation,
    )

    if console:
        console.print(rendered)

    if halt:
        raise StrictLLMFallbackBlockedError(
            provider=provider,
            model_name=model_name,
            status_code=status_code,
            message=message or f"HTTP {status_code} Error",
            detail=detail,
            endpoint=endpoint or "",
        )

    return rendered
