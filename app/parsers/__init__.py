from app.parsers.base import BaseParser, ParseResult, ParserError
from app.parsers.doc import DocParser
from app.parsers.docx import DocxParser
from app.parsers.pdf import PdfParser
from app.parsers.rtf import RtfParser
from app.parsers.spreadsheet import XlsParser
from app.parsers.text import PlainTextParser

PARSERS: list[BaseParser] = [
    PdfParser(),
    DocxParser(),
    RtfParser(),
    DocParser(),
    XlsParser(),
    PlainTextParser(),
]

