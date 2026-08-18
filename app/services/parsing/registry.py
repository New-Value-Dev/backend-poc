from __future__ import annotations

from app.services.parsing.base import DocumentParser
from app.services.parsing.docx_parser import DocxParser
from app.services.parsing.hwpx_parser import HwpxParser
from app.services.parsing.ocr import TesseractProvider
from app.services.parsing.pdf_parser import PdfParser
from app.services.parsing.text_parser import TextParser

# OCR provider 는 한 번만 만들어 PDF 파서에 주입
_ocr = TesseractProvider(lang="kor+eng")

_PARSERS: list[DocumentParser] = [
    TextParser(),
    DocxParser(),
    PdfParser(ocr=_ocr),
    HwpxParser(),
]

_BY_EXT: dict[str, DocumentParser] = {
    ext: parser for parser in _PARSERS for ext in parser.extensions
}


def get_parser(extension: str) -> DocumentParser | None:
    return _BY_EXT.get(extension.lower().lstrip("."))


def supported_extensions() -> list[str]:
    return sorted(_BY_EXT)
