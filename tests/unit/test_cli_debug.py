"""Unit tests for ARC CLI Replay & Local Debugger Proxy (`arc debug` & `arc repro`)."""

import socket
from collections.abc import Generator

import pytest
from typer.testing import CliRunner

from cli.main import app
from cli.proxy.debugger_proxy import LocalDebuggerProxy

runner = CliRunner()


@pytest.fixture(autouse=True)
def cleanup_proxies() -> Generator[None, None, None]:
    """Fixture to ensure all proxies are stopped before and after each test."""
    LocalDebuggerProxy.stop_all()
    yield
    LocalDebuggerProxy.stop_all()


def test_cli_repro_command_executes_reproducer() -> None:
    """Happy Path 1: `arc repro` reads reproducer YAML and outputs Rich verdict table."""
    result = runner.invoke(app, ["repro", "tests/fixtures/arc-repro-sample.yaml"])
    assert result.exit_code == 0
    output_lower = result.output.lower()
    assert "violated invariant" in output_lower
    assert "double_refund_invariant" in result.output
    assert "reproduce rate" in output_lower


def test_cli_debug_starts_proxy_and_prints_env() -> None:
    """Happy Path 2: `arc debug` starts proxy and prints export env statements."""
    result = runner.invoke(
        app,
        ["debug", "--repro", "tests/fixtures/arc-repro-sample.yaml", "--port", "8089"],
    )
    assert result.exit_code == 0
    assert "export HTTP_PROXY=http://127.0.0.1:8089" in result.output
    assert "export LLM_API_BASE=http://127.0.0.1:8089/v1" in result.output


def test_cli_repro_file_not_found() -> None:
    """Edge Case 1: `arc repro` with missing file returns exit code 1 and error message."""
    result = runner.invoke(app, ["repro", "non_existent_file.yaml"])
    assert result.exit_code == 1
    assert "Error: Reproducer file not found" in result.output


def test_cli_debug_port_conflict_fallback() -> None:
    """Edge Case 2: Port conflict triggers fallback to next available port (e.g. 8090)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 8089))
    sock.listen(1)
    try:
        result = runner.invoke(
            app,
            ["debug", "--repro", "tests/fixtures/arc-repro-sample.yaml", "--port", "8089"],
        )
        assert result.exit_code == 0
        assert "export HTTP_PROXY=http://127.0.0.1:8090" in result.output
        assert "export LLM_API_BASE=http://127.0.0.1:8090/v1" in result.output
    finally:
        sock.close()
