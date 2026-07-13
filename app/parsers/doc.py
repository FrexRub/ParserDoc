from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.parsers.base import BaseParser, ParseResult, ParserError
from app.services.normalizer import normalize_text


_PRINTABLE_RUN = re.compile(r"[^\x00-\x08\x0e-\x1f]{4,}")
_READABLE_CHAR = re.compile(r"[0-9A-Za-z\u0400-\u04ff]")
_LEADING_NOISE = re.compile(r"^[^0-9A-Za-z\u0400-\u04ff]+")


def _clean_doc_run(text: str) -> str:
    text = text.replace("\x0b", "\n").replace("\x0c", "\n")
    text = re.sub(r"[\uf020-\uf0ff]", " ", text)
    text = re.sub(r"[\x00-\x08\x0e-\x1f]", " ", text)
    text = _LEADING_NOISE.sub("", text)
    return normalize_text(text)


def _looks_like_text(text: str) -> bool:
    readable = sum(1 for char in text if _READABLE_CHAR.match(char))
    return readable >= 4 and readable / max(len(text), 1) >= 0.15


def _best_effort_binary_doc_text(content: bytes) -> str:
    candidates: list[str] = []

    utf16_text = content.decode("utf-16le", errors="ignore")
    for run in _PRINTABLE_RUN.findall(utf16_text):
        cleaned = _clean_doc_run(run)
        if _looks_like_text(cleaned):
            candidates.append(cleaned)

    for encoding in ("utf-8", "cp1251", "cp1252", "latin-1"):
        decoded = content.decode(encoding, errors="ignore")
        for run in _PRINTABLE_RUN.findall(decoded):
            cleaned = _clean_doc_run(run)
            if _looks_like_text(cleaned):
                candidates.append(cleaned)

    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        key = candidate.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)

    return normalize_text("\n".join(unique))


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
        converter_error: str | None = None

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
                    converter_error = output.stdout or output.stderr

        text = _best_effort_binary_doc_text(content)
        if text:
            return ParseResult(
                text=text,
                source_type="doc",
                warnings=["DOC parsed with built-in best-effort text extraction; install LibreOffice for higher fidelity."],
            )

        if converter_error:
            raise ParserError(converter_error)

        raise ParserError(
            "DOC parsing requires antiword, catdoc, or LibreOffice/soffice to be installed on the server."
        )

