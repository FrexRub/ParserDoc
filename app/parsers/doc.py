from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from app.parsers.base import BaseParser, ParseResult, ParserError
from app.services.normalizer import normalize_text


class DocParser(BaseParser):
    def can_handle(self, filename: str, mime_type: str | None) -> bool:
        return filename.lower().endswith(".doc") or mime_type in {
            "application/msword",
            "application/vnd.ms-word",
        }

    def extract(self, content: bytes, filename: str, mime_type: str | None) -> ParseResult:
        antiword = shutil.which("antiword")
        catdoc = shutil.which("catdoc")
        soffice = shutil.which("soffice") or shutil.which("libreoffice")

        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / filename
            src.write_bytes(content)

            if antiword:
                output = subprocess.run([antiword, str(src)], capture_output=True, text=True, check=False)
                text = output.stdout or output.stderr
                if output.returncode == 0 and text.strip():
                    return ParseResult(text=normalize_text(text), source_type="doc")

            if catdoc:
                output = subprocess.run([catdoc, str(src)], capture_output=True, text=True, check=False)
                text = output.stdout or output.stderr
                if output.returncode == 0 and text.strip():
                    return ParseResult(text=normalize_text(text), source_type="doc")

            if soffice:
                outdir = Path(tmpdir) / "out"
                outdir.mkdir(parents=True, exist_ok=True)
                output = subprocess.run(
                    [soffice, "--headless", "--convert-to", "txt:Text", "--outdir", str(outdir), str(src)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                converted = next(outdir.glob("*.txt"), None)
                if converted and converted.exists():
                    text = converted.read_text(encoding="utf-8", errors="ignore")
                    return ParseResult(text=normalize_text(text), source_type="doc")
                if output.stdout or output.stderr:
                    raise ParserError(output.stdout or output.stderr)

        raise ParserError(
            "DOC parsing requires antiword, catdoc, or LibreOffice/soffice to be installed on the server."
        )

