from __future__ import annotations

import json
import socket
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

PAGES_DIR = Path(__file__).parent / "pages"
STATIC_DIR = Path(__file__).parent / "static"


class FixtureHandler(SimpleHTTPRequestHandler):
    mutation_log: list[dict] = []  # noqa: RUF012

    def do_GET(self) -> None:
        if self.path == "/api/mutations":
            self._json_response(self.mutation_log)
            return

        if self.path == "/api/expire-session":
            self._serve_expired_page()
            return

        file_path = self._resolve_path()
        if file_path and file_path.exists():
            self._serve_file(file_path)
        else:
            self.send_error(404, f"Not found: {self.path}")

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else b""

        self.mutation_log.append(
            {
                "method": "POST",
                "path": self.path,
                "body": body.decode("utf-8", errors="replace"),
            }
        )

        self._json_response({"status": "recorded"})

    def _resolve_path(self) -> Path | None:
        url_path = self.path.split("?")[0].split("#")[0]

        if url_path == "/":
            return PAGES_DIR / "index.html"

        if url_path.startswith("/static/"):
            rel = url_path[len("/static/") :]
            return STATIC_DIR / rel

        if url_path.startswith("/"):
            rel = url_path[1:]
            candidate = PAGES_DIR / rel
            if candidate.exists():
                return candidate

        return None

    def _serve_file(self, path: Path) -> None:
        content = path.read_bytes()
        content_type = "text/html"
        if path.suffix == ".css":
            content_type = "text/css"
        elif path.suffix == ".js":
            content_type = "application/javascript"
        elif path.suffix == ".json":
            content_type = "application/json"
        elif path.suffix == ".png":
            content_type = "image/png"

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_expired_page(self) -> None:
        html = b"""<!DOCTYPE html><html><body>
        <div id="login-form"><h1>Session Expired</h1><p>Please log in again.</p></div>
        </body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def _json_response(self, data) -> None:
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args) -> None:
        pass


class FixtureServer:
    def __init__(self) -> None:
        self.port = self._find_free_port()
        self.handler_class = type("Handler", (FixtureHandler,), {"mutation_log": []})
        self.server = HTTPServer(("127.0.0.1", self.port), self.handler_class)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        if self._thread:
            self._thread.join(timeout=5)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def mutation_log(self) -> list[dict]:
        return self.handler_class.mutation_log

    def clear_mutations(self) -> None:
        self.handler_class.mutation_log.clear()

    @staticmethod
    def _find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]
