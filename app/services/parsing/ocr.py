"""OCR 추상화. 지금은 Tesseract 구현.

나중에 EasyOCR/PaddleOCR/클라우드로 교체할 수 있도록 OCRProvider 인터페이스를 유지한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import cv2
import numpy as np
import pytesseract
from PIL import Image

_MAX_SKEW_DEG = 15.0  # 이보다 크게 추정되면 오검출로 보고 회전을 건너뜀


@dataclass
class OCRWord:
    text: str
    bbox: list[float]  # [x0, y0, x1, y1] (이미지 픽셀 좌표)
    confidence: float  # 0~100


class OCRProvider(Protocol):
    def recognize(self, image: Image.Image) -> list[OCRWord]: ...


def preprocess_for_ocr(image: Image.Image) -> Image.Image:
    """그레이스케일 변환 + 디스큐(기울기 보정) + CLAHE 대비 보정.

    OCR 엔진(Tesseract/EasyOCR/...)에 관계없이 재사용하는 전처리 단계라
    특정 OCRProvider 구현이 아니라 모듈 레벨 함수로 둔다. 이진화는 하지 않음 —
    Tesseract LSTM 엔진은 내부적으로 자체 Otsu 이진화를 수행하므로 미리
    하드 이진화해서 넘기면 정보 손실로 인식률이 오히려 떨어지는 경우가 많다.
    """
    gray = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)

    angle = _estimate_skew(gray)
    if angle and abs(angle) <= _MAX_SKEW_DEG:
        h, w = gray.shape
        center = (w / 2, h / 2)
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        gray = cv2.warpAffine(
            gray, matrix, (w, h),
            flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=255,
        )

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    return Image.fromarray(enhanced)


def _estimate_skew(gray: np.ndarray) -> float:
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thresh > 0))
    if coords.shape[0] < 20:
        return 0.0
    rect_angle = cv2.minAreaRect(coords)[-1]
    if rect_angle < -45:
        return -(90 + rect_angle)
    return -rect_angle


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
