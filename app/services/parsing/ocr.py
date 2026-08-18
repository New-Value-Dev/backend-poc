"""OCR 추상화. 지금은 Tesseract 구현.

나중에 EasyOCR/PaddleOCR/클라우드로 교체할 수 있도록 OCRProvider 인터페이스를 유지한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pytesseract
from PIL import Image


@dataclass
class OCRWord:
    text: str
    bbox: list[float]  # [x0, y0, x1, y1] (이미지 픽셀 좌표)
    confidence: float  # 0~100


class OCRProvider(Protocol):
    def recognize(self, image: Image.Image) -> list[OCRWord]: ...


class TesseractProvider:
    name = "tesseract"

    def __init__(self, lang: str = "kor+eng") -> None:
        self.lang = lang

    def recognize(self, image: Image.Image) -> list[OCRWord]:
        data = pytesseract.image_to_data(
            image, lang=self.lang, output_type=pytesseract.Output.DICT
        )
        words: list[OCRWord] = []
        for i, text in enumerate(data["text"]):
            text = (text or "").strip()
            if not text:
                continue
            try:
                conf = float(data["conf"][i])
            except (ValueError, TypeError):
                conf = -1.0
            if conf < 0:
                continue
            x, y, w, h = (
                data["left"][i],
                data["top"][i],
                data["width"][i],
                data["height"][i],
            )
            words.append(
                OCRWord(text=text, bbox=[float(x), float(y), float(x + w), float(y + h)], confidence=conf)
            )
        return words
