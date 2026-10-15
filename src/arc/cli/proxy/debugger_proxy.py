"""Local Debugger Proxy Engine for ARC CLI (`arc debug`).

Acts as an intercepting replay & chaos proxy server that can simulate LLM completions
and inject reproducer fault specifications into live agent debugger sessions.
"""

from __future__ import annotations

import http.server
import json
import logging
import socket
import socketserver
import threading
from pathlib import Path
from types import TracebackType
from typing import Any, ClassVar

import yaml
from typing_extensions import Self

logger = logging.getLogger(__name__)


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a TCP port is currently bound/in use on host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def find_available_port(
    start_port: int, host: str = "127.0.0.1", max_attempts: int = 100
) -> tuple[int, bool]:
    """Find an available port starting from start_port.

    Returns (port, fallback_occurred).
    """
    current_port = start_port
    fallback_occurred = False
    for _ in range(max_attempts):
        if not is_port_in_use(current_port, host):
            return current_port, fallback_occurred
        current_port += 1
        fallback_occurred = True
    raise RuntimeError(
        f"Could not find available port in range {start_port}-{current_port}"
    )


class ReplayProxyHandler(http.server.BaseHTTPRequestHandler):
    """Replay proxy request handler capable of injecting reproducer faults."""

    server: Any  # Reference to ThreadedTCPServer

    def do_GET(self) -> None:
        """Handles GET requests (health checks, status, trace inspection)."""
        if self.path in ("/healthz", "/status", "/v1/health"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            status_payload = {
                "status": "healthy",
                "proxy_mode": "arc_replay_debugger",
                "repro_loaded": bool(getattr(self.server, "repro_data", None)),
                "faults_configured": len(getattr(self.server, "faults", [])),
                "step_counter": getattr(self.server, "step_counter", 0),
            }
            self.wfile.write(json.dumps(status_payload).encode("utf-8"))
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        response_body = b'{"status": "ok", "mode": "arc_debug_replay"}'
        self.wfile.write(response_body)

    def do_POST(self) -> None:
        """Handles POST requests, applying matching reproducer faults or OpenAI-compatible responses."""
        content_length = int(self.headers.get("Content-Length", 0))
        req_body = self.rfile.read(content_length) if content_length > 0 else b"{}"

        # Increment step counter
        if not hasattr(self.server, "step_counter"):
            self.server.step_counter = 0
        self.server.step_counter += 1
        current_step = self.server.step_counter

        faults: list[dict[str, Any]] = getattr(self.server, "faults", [])
        active_fault: dict[str, Any] | None = None

        for f in faults:
            f_step = int(f.get("at_step") or f.get("step") or 0)
            if f_step in (current_step, 0):
                active_fault = f
                break

        # If a fault matches this step, simulate the fault directly
        if active_fault:
            fault_type = str(active_fault.get("type") or active_fault.get("fault_type") or "")
            if fault_type in ("timeout_after_commit", "timeout_before_commit"):
                self.send_response(504)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps({
                        "error": "Gateway Timeout",
                        "status_code": 504,
                        "detail": f"ARC Debugger Proxy injected fault: {fault_type}",
                        "step": current_step,
                    }).encode("utf-8")
                )
                return

            if fault_type == "http_500":
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps({
                        "error": "Internal Server Error",
                        "status_code": 500,
                        "detail": "ARC Debugger Proxy injected HTTP 500",
                        "step": current_step,
                    }).encode("utf-8")
                )
                return

            if fault_type == "http_429":
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps({
                        "error": "Too Many Requests",
                        "status_code": 429,
                        "detail": "ARC Debugger Proxy injected HTTP 429 rate limit",
                        "step": current_step,
                    }).encode("utf-8")
                )
                return

        # OpenAI-compatible completions endpoint emulation
        if "/chat/completions" in self.path or "/completions" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            completion_payload = {
                "id": f"chatcmpl-arc-debug-{current_step}",
                "object": "chat.completion",
                "created": 1700000000,
                "model": "arc-replay-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": f"ARC Replay Proxy simulated response for step {current_step}",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            }
            self.wfile.write(json.dumps(completion_payload).encode("utf-8"))
            return

        # Default standard 200 response
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        response_body = json.dumps({
            "status": "ok",
            "mode": "arc_debug_replay",
            "step": current_step,
        }).encode("utf-8")
        self.wfile.write(response_body)

    def log_message(self, format: str, *args: Any) -> None:
        # Silence noisy HTTP connection logs
        pass


class LocalDebuggerProxy:
    """Manager for the local debug proxy process / server."""

    _active_proxies: ClassVar[list[LocalDebuggerProxy]] = []

    def __init__(
        self,
        repro_file: str | None = None,
        requested_port: int = 8089,
        host: str = "127.0.0.1",
    ) -> None:
        self.repro_file = repro_file
        self.requested_port = requested_port
        self.host = host
        self.bound_port = requested_port
        self.fallback_occurred = False
        self.server: socketserver.TCPServer | None = None
        self.server_thread: threading.Thread | None = None
        self._is_running = False
        self.repro_data: dict[str, Any] = {}
        self.faults: list[dict[str, Any]] = []

        # Load reproducer data if specified
        if self.repro_file:
            path = Path(self.repro_file)
            if path.exists() and path.is_file():
                try:
                    with open(path, encoding="utf-8") as f_in:
                        self.repro_data = yaml.safe_load(f_in) or {}
                    raw_faults = self.repro_data.get("faults") or self.repro_data.get("fault") or []
                    if isinstance(raw_faults, list):
                        self.faults = [f for f in raw_faults if isinstance(f, dict)]
                    elif isinstance(raw_faults, dict):
                        self.faults = [raw_faults]
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Could not parse reproducer file for proxy: %s", exc)

    def start(self) -> tuple[int, bool]:
        """Start the proxy server.

        Returns (bound_port, fallback_occurred).
        """
        self.bound_port, self.fallback_occurred = find_available_port(
            self.requested_port, self.host
        )

        class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
            allow_reuse_address = True
            repro_data: dict[str, Any] = self.repro_data
            faults: list[dict[str, Any]] = self.faults
            step_counter: int = 0

        self.server = ThreadedTCPServer(
            (self.host, self.bound_port), ReplayProxyHandler
        )
        self.server_thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.server_thread.start()
        self._is_running = True
        LocalDebuggerProxy._active_proxies.append(self)

        return self.bound_port, self.fallback_occurred

    def get_env_vars(self) -> dict[str, str]:
        """Return environment variable settings for developer export."""
        return {
            "HTTP_PROXY": f"http://{self.host}:{self.bound_port}",
            "LLM_API_BASE": f"http://{self.host}:{self.bound_port}/v1",
        }

    def stop(self) -> None:
        """Stop the proxy server cleanly."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=1.0)
        self._is_running = False
        if self in LocalDebuggerProxy._active_proxies:
            LocalDebuggerProxy._active_proxies.remove(self)

    @classmethod
    def stop_all(cls) -> None:
        """Stop all currently active proxy instances."""
        for proxy in list(cls._active_proxies):
            proxy.stop()

    @property
    def is_running(self) -> bool:
        return self._is_running

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.stop()
