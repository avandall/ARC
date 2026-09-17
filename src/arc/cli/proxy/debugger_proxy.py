"""Local Debugger Proxy Engine for ARC CLI (`arc debug`)."""

import http.server
import logging
import socket
import socketserver
import threading
from types import TracebackType
from typing import Any, ClassVar

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
    """Simple replay proxy request handler for debugging."""

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        response_body = b'{"status": "ok", "mode": "arc_debug_replay"}'
        self.wfile.write(response_body)

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        _ = self.rfile.read(content_length)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        response_body = b'{"status": "ok", "mode": "arc_debug_replay"}'
        self.wfile.write(response_body)

    def log_message(self, format: str, *args: Any) -> None:
        # Silence standard HTTP logs during proxy operation
        pass


class LocalDebuggerProxy:
    """Manager for the local debug proxy process / server."""

    _active_proxies: ClassVar[list["LocalDebuggerProxy"]] = []

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

    def start(self) -> tuple[int, bool]:
        """Start the proxy server.

        Returns (bound_port, fallback_occurred).
        """
        self.bound_port, self.fallback_occurred = find_available_port(
            self.requested_port, self.host
        )

        class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
            allow_reuse_address = True

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
