from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

from app.parsers.docx import DocxParser
from app.parsers.text import PlainTextParser
from app.services.normalizer import normalize_text
from serve import Handler, parse_document


def make_docx(text: str) -> bytes:
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>{text}</w:t></w:r></w:p>
  </w:body>
</w:document>
"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


class CoreParsingTests(unittest.TestCase):
    def test_normalize_text_compacts_blank_lines(self) -> None:
        self.assertEqual(normalize_text("one\r\n\r\n\r\n two \t\n"), "one\n\n two")

    def test_plain_text_parser_extracts_utf8_text(self) -> None:
        result = PlainTextParser().extract("hello\n\nworld".encode("utf-8"), "sample.txt", "text/plain")

        self.assertEqual(result.source_type, "txt")
        self.assertEqual(result.text, "hello\n\nworld")

    def test_docx_parser_extracts_document_text(self) -> None:
        result = DocxParser().extract(make_docx("Hello DOCX"), "sample.docx", None)

        self.assertEqual(result.source_type, "docx")
        self.assertEqual(result.text, "Hello DOCX")

    def test_parse_document_returns_structured_response(self) -> None:
        result = parse_document("sample.txt", "text/plain", b"hello")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["source_type"], "txt")
        self.assertEqual(result["text"], "hello")
        self.assertEqual(result["characters"], 5)


class ServeEndpointTests(unittest.TestCase):
    def test_raw_endpoint_parses_text_file(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/parse/raw?filename=sample.txt&mime_type=text/plain",
                data=b"from raw body",
                method="POST",
                headers={"Content-Type": "text/plain"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["text"], "from raw body")

    def test_home_page_is_served(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
                body = response.read().decode("utf-8")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertIn("ParserDoc test panel", body)


if __name__ == "__main__":
    unittest.main()
