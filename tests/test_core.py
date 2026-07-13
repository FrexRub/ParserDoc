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
from unittest.mock import patch

from app.parsers.doc import DocParser
from app.parsers.docx import DocxParser
from app.parsers.rtf import RtfParser
from app.parsers.text import PlainTextParser
from app.services.normalizer import normalize_text
from serve import Handler, parse_document


def chars(*codes: int) -> str:
    return "".join(chr(code) for code in codes)


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

    def test_rtf_parser_extracts_ansi_encoded_text(self) -> None:
        content = (
            r"{\rtf1\ansi\ansicpg1251{\fonttbl{\f0 Calibri;}}"
            r"\f0 \'cf\'f0\'e8\'e2\'e5\'f2\par world}"
        ).encode("ascii")

        result = RtfParser().extract(content, "sample.rtf", "text/rtf")

        self.assertEqual(result.source_type, "rtf")
        self.assertEqual(result.text, chars(1055, 1088, 1080, 1074, 1077, 1090) + "\nworld")

    def test_doc_parser_uses_binary_fallback_without_external_tools(self) -> None:
        title = chars(1047, 1072, 1075, 1086, 1083, 1086, 1074, 1086, 1082)
        body = chars(1058, 1077, 1082, 1089, 1090, 32, 1076, 1086, 1082, 1091, 1084, 1077, 1085, 1090, 1072)
        content = b"\xd0\xcf\x11\xe0" + f"{title}\n{body}".encode("utf-16le")

        with patch("app.parsers.doc.shutil.which", return_value=None):
            result = DocParser().extract(content, "sample.doc", "application/msword")

        self.assertEqual(result.source_type, "doc")
        self.assertIn(title, result.text)
        self.assertIn(body, result.text)
        self.assertTrue(result.warnings)

    def test_doc_parser_extracts_word_document_text_without_ole_noise(self) -> None:
        fixture = next(Path("docs").glob("*.doc"))

        result = DocParser().extract(fixture.read_bytes(), fixture.name, "application/msword")

        self.assertIn("https://www.youtube.com/watch?v=nNh4rJR-1DM", result.text)
        self.assertNotIn("HYPERLINK", result.text)
        self.assertNotIn("Root Entry", result.text)
        self.assertNotIn("Content_Types", result.text)

    def test_parse_document_returns_structured_response(self) -> None:
        result = parse_document("sample.txt", "text/plain", b"hello")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["source_type"], "txt")
        self.assertEqual(result["text"], "hello")
        self.assertEqual(result["characters"], 5)

    def test_parse_document_prefers_rtf_extension_over_msword_mime_type(self) -> None:
        content = (
            r"{\rtf1\ansi\ansicpg1251{\fonttbl{\f0 Calibri;}}"
            r"\f0 \'cf\'f0\'e8\'e2\'e5\'f2}"
        ).encode("ascii")

        result = parse_document("sample.rtf", "application/msword", content)

        self.assertEqual(result["source_type"], "rtf")
        self.assertEqual(result["text"], chars(1055, 1088, 1080, 1074, 1077, 1090))

    def test_parse_document_ignores_rtf_theme_hex_data_after_links(self) -> None:
        content = (
            r"{\rtf1\ansi "
            r"{\field{\*\fldinst HYPERLINK \"https://example.com\"}"
            r"{\fldrslt https://example.com}}"
            r"{\*\themedata 3c3f786d6c2076657273696f6e3d22312e30223f3e}"
            r"}"
        ).encode("ascii")

        result = parse_document("sample.rtf", "application/msword", content)

        self.assertEqual(result["text"], "https://example.com")
        self.assertNotIn("3c3f786d", result["text"])

    def test_parse_document_repairs_mojibake_filename(self) -> None:
        filename = chars(1042, 1080, 1076, 1077, 1086, 95, 1088, 1072, 1079, 1073, 1086, 1088) + ".txt"
        mojibake = filename.encode("utf-8").decode("cp1251")

        result = parse_document(mojibake, "text/plain", b"hello")

        self.assertEqual(result["filename"], filename)


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
