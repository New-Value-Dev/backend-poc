from __future__ import annotations

import statistics
from pathlib import Path

import fitz
from PIL import Image

from app.services.parsing.base import (
    BODY_LEVEL,
    UnifiedDocument,
    UnifiedSection,
)
from app.services.parsing.ocr import OCRProvider, OCRWord, preprocess_for_ocr

OCR_DPI = 200
_MIN_NATIVE_CHARS = 3  # 이보다 텍스트가 적으면 스캔본으로 보고 OCR
OCR_LOW_CONFIDENCE_THRESHOLD = 60.0  # 이 미만이면 재확인이 필요한 줄로 표시


class PdfParser:
    name = "pdf"
    extensions = ("pdf",)

    def __init__(self, ocr: OCRProvider | None = None) -> None:
        self.ocr = ocr

    def parse(self, path: Path) -> UnifiedDocument:
        doc = fitz.open(str(path))
        page_count = doc.page_count
        sections: list[UnifiedSection] = []
        order = 0
        ocr_used = False
        ocr_line_count = 0
        ocr_low_conf_count = 0
        try:
            for page_index in range(page_count):
                page = doc[page_index]
                page_no = page_index + 1
                native_text = page.get_text("text").strip()

                if len(native_text) >= _MIN_NATIVE_CHARS:
                    order = self._parse_native_page(page, page_no, sections, order)
                elif self.ocr is not None:
                    order, did_ocr, line_count, low_conf_count = self._parse_ocr_page(
                        page, page_no, sections, order
                    )
                    ocr_used = ocr_used or did_ocr
                    ocr_line_count += line_count
                    ocr_low_conf_count += low_conf_count
                else:
                    sections.append(
                        UnifiedSection(
                            content="[스캔 페이지 — OCR 미사용]",
                            order=order, page_start=page_no, page_end=page_no,
                            section_type="image", meta={"needs_ocr": True},
                        )
                    )
                    order += 1
        finally:
            doc.close()

        doc_meta: dict = {}
        if ocr_used:
            doc_meta["ocr_line_count"] = ocr_line_count
            doc_meta["ocr_low_confidence_count"] = ocr_low_conf_count

        return UnifiedDocument(
            sections=sections, parser_name=self.name,
            page_count=page_count, ocr_used=ocr_used,
            meta=doc_meta,
        )

    def _parse_native_page(self, page, page_no, sections, order) -> int:
        data = page.get_text("dict")
        blocks = [b for b in data.get("blocks", []) if b.get("type") == 0]
        sizes = [
            span["size"]
            for b in blocks for line in b.get("lines", []) for span in line.get("spans", [])
        ]
        body_size = statistics.median(sizes) if sizes else 0.0

        for block in blocks:
            spans = [s for line in block.get("lines", []) for s in line.get("spans", [])]
            text = " ".join(s["text"] for s in spans).strip()
            if not text:
                continue
            max_size = max((s["size"] for s in spans), default=0.0)
            is_heading = (
                body_size > 0 and max_size >= body_size * 1.3 and len(text) <= 120
            )
            sections.append(
                UnifiedSection(
                    content=text,
                    title=text if is_heading else None,
                    order=order,
                    level=1 if is_heading else BODY_LEVEL,
                    section_type="heading" if is_heading else "paragraph",
                    page_start=page_no, page_end=page_no,
                    meta={"bbox": [round(v, 1) for v in block["bbox"]], "font_size": round(max_size, 1)},
                )
            )
            order += 1
        return order

    def _parse_ocr_page(self, page, page_no, sections, order) -> tuple[int, bool, int, int]:
        zoom = OCR_DPI / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        image = preprocess_for_ocr(image)
        words = self.ocr.recognize(image)
        if not words:
            return order, True, 0, 0

        lines = _group_lines(words)
        line_heights = [_line_height(line_words) for line_words in lines]
        positive_heights = [h for h in line_heights if h > 0]
        body_height = statistics.median(positive_heights) if positive_heights else 0.0

        line_count = 0
        low_conf_count = 0
        for line_words, line_height in zip(lines, line_heights):
            text = " ".join(w.text for w in line_words).strip()
            if not text:
                continue
            xs0 = min(w.bbox[0] for w in line_words) / zoom
            ys0 = min(w.bbox[1] for w in line_words) / zoom
            xs1 = max(w.bbox[2] for w in line_words) / zoom
            ys1 = max(w.bbox[3] for w in line_words) / zoom
            avg_conf = round(sum(w.confidence for w in line_words) / len(line_words), 1)
            is_heading = (
                body_height > 0 and line_height >= body_height * 1.3 and len(text) <= 120
            )
            low_confidence = avg_conf < OCR_LOW_CONFIDENCE_THRESHOLD
            sections.append(
                UnifiedSection(
                    content=text,
                    title=text if is_heading else None,
                    order=order,
                    level=1 if is_heading else BODY_LEVEL,
                    section_type="heading" if is_heading else "paragraph",
                    page_start=page_no, page_end=page_no,
                    meta={
                        "bbox": [round(xs0, 1), round(ys0, 1), round(xs1, 1), round(ys1, 1)],
                        "ocr": True, "confidence": avg_conf,
                        "line_height": round(line_height / zoom, 1),
                        "low_confidence": low_confidence,
                    },
                )
            )
            order += 1
            line_count += 1
            low_conf_count += 1 if low_confidence else 0
        return order, True, line_count, low_conf_count


def _line_height(line_words: list[OCRWord]) -> float:
    if not line_words:
        return 0.0
    return max(w.bbox[3] for w in line_words) - min(w.bbox[1] for w in line_words)


def _group_lines(words: list[OCRWord]) -> list[list[OCRWord]]:
    """y 좌표 근접도로 단어를 라인 단위로 묶는다."""
    if not words:
        return []
    heights = [w.bbox[3] - w.bbox[1] for w in words]
    tol = (statistics.median(heights) or 10) * 0.6
    ordered = sorted(words, key=lambda w: (w.bbox[1], w.bbox[0]))
    lines: list[list[OCRWord]] = []
    current: list[OCRWord] = []
    current_y: float | None = None
    for w in ordered:
        y = w.bbox[1]
        if current_y is None or abs(y - current_y) <= tol:
            current.append(w)
            current_y = y if current_y is None else current_y
        else:
            lines.append(sorted(current, key=lambda x: x.bbox[0]))
            current = [w]
            current_y = y
    if current:
        lines.append(sorted(current, key=lambda x: x.bbox[0]))
    return lines
