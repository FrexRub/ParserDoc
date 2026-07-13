from __future__ import annotations

import asyncio
import cgi
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.models import ErrorResponse
from app.parsers.base import ParserError
from app.services.extractor import DocumentExtractor, DocumentPayload
from app.settings import settings

BASE_DIR = Path(__file__).resolve().parent
INDEX_HTML = BASE_DIR / "app" / "static" / "index.html"
EXTRACTOR = DocumentExtractor()


def json_bytes(payload: dict, status: int = 200) -> tuple[int, bytes]:
    return status, json.dumps(payload, ensure_ascii=False).encode("utf-8")


def parse_document(filename: str, mime_type: str | None, content: bytes) -> dict:
    payload = DocumentPayload(filename=filename, mime_type=mime_type, content=content)
    return asyncio.run(EXTRACTOR.extract(payload)).model_dump()


class Handler(BaseHTTPRequestHandler):
    server_version = "ParserDoc/0.1"

    def _send(self, status: int, body: bytes, content_type: str = "text/plain; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        code, body = json_bytes(payload, status)
        self._send(code, body, "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            body = INDEX_HTML.read_bytes()
            self._send(200, body, "text/html; charset=utf-8")
            return
        if parsed.path == "/health":
            self._send_json({"status": "ok"})
            return
        self._send_json({"status": "error", "error": "not_found", "detail": "Route not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/parse":
            self._handle_multipart()
            return
        if parsed.path == "/parse/raw":
            self._handle_raw(parsed.query)
            return
        self._send_json({"status": "error", "error": "not_found", "detail": "Route not found"}, 404)

    def _handle_raw(self, query: str) -> None:
        try:
            params = parse_qs(query)
            filename = params.get("filename", ["document"])[0]
            mime_type = params.get("mime_type", [None])[0]
            length = int(self.headers.get("Content-Length", "0"))
            if length > settings.max_upload_bytes:
                self._send_json({"status": "error", "error": "request_error", "detail": "File too large"}, 413)
                return
            content = self.rfile.read(length)
            result = parse_document(filename, mime_type, content)
            self._send_json(result)
        except ParserError as exc:
            self._send_json(ErrorResponse(error="request_error", detail=str(exc)).model_dump(), 422)
        except Exception as exc:  # noqa: BLE001
            self._send_json(ErrorResponse(error="request_error", detail=str(exc)).model_dump(), 500)

    def _handle_multipart(self) -> None:
        try:
            content_type = self.headers.get("Content-Type")
            if not content_type:
                self._send_json({"status": "error", "error": "request_error", "detail": "Missing Content-Type"}, 400)
                return

            length = int(self.headers.get("Content-Length", "0"))
            if length > settings.max_upload_bytes:
                self._send_json({"status": "error", "error": "request_error", "detail": "File too large"}, 413)
                return

            env = {
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": str(length),
            }
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ=env,
                keep_blank_values=True,
            )
            field = form["file"] if "file" in form else None
            if field is None or not getattr(field, "filename", None):
                self._send_json({"status": "error", "error": "request_error", "detail": "File field is required"}, 400)
                return

            content = field.file.read()
            if len(content) > settings.max_upload_bytes:
                self._send_json({"status": "error", "error": "request_error", "detail": "File too large"}, 413)
                return

            filename = field.filename or "document"
            mime_type = getattr(field, "type", None)
            result = parse_document(filename, mime_type, content)
            self._send_json(result)
        except ParserError as exc:
            self._send_json(ErrorResponse(error="request_error", detail=str(exc)).model_dump(), 422)
        except Exception as exc:  # noqa: BLE001
            self._send_json(ErrorResponse(error="request_error", detail=str(exc)).model_dump(), 500)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def main() -> None:
    host = os.environ.get("PARSERDOC_HOST", "127.0.0.1")
    port = int(os.environ.get("PARSERDOC_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"ParserDoc test server running at http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
