from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class LLMError(Exception):
    """LLM 호출 실패(네트워크/응답 파싱 등)."""


class LLMConfigError(LLMError):
    """LLM provider 설정 문제(예: OpenAI 키 없음)."""


@dataclass
class ProofreadFinding:
    """교정 제안 1건. GPT/규칙 provider 공통 반환 단위."""

    original: str  # 원문 표현
    suggestion: str  # 교정안
    reason: str  # 교정 이유(사용자 노출)
    # spelling(맞춤법) / spacing(띄어쓰기) / grammar(문법) / expression(표현)
    category: str = "spelling"


@runtime_checkable
class LLMProvider(Protocol):
    """LLM provider 인터페이스. proofread 외 모듈도 이 뒤에 붙는다."""

    name: str

    def proofread(self, text: str) -> list[ProofreadFinding]:
        """text 를 검토해 교정 제안 목록을 반환한다."""
        ...

    def proofread_batch(self, texts: list[str]) -> list[list[ProofreadFinding]]:
        """여러 텍스트를 한 번에 검토. 반환은 입력 순서와 1:1 대응(길이 동일)."""
        ...
