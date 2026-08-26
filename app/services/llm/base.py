from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
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


@dataclass
class RagContext:
    """RAG 프롬프트에 넣는 근거 조각 1개."""

    index: int  # 프롬프트에 노출되는 [n] 번호. 답변의 인용 표기와 citations 를 잇는 키다.
    content: str
    label: str  # 출처 표시용 ("문서명 > 상위 heading > p.3")


@dataclass
class RagAnswer:
    """RAG 답변 1건. cited_indexes 는 RagContext.index 목록."""

    answer: str
    cited_indexes: list[int]
    confidence: float | None = None


@dataclass
class QuizDraft:
    """LLM이 만든 문항 초안 1개. 아직 검증 전이라 그대로 DB에 넣지 않는다.

    `source_index` 는 프롬프트에 준 RagContext.index — 어느 근거에서 나온 문항인지
    되짚어 출처(source_document_id/source_location)를 채우는 데 쓴다.
    """

    type: str  # SINGLE_CHOICE | TRUE_FALSE | SHORT_ANSWER
    text: str
    correct_answer: str
    explanation: str
    options: list[str] | None = None
    difficulty: str = "MEDIUM"
    tags: list[str] = field(default_factory=list)
    source_index: int | None = None


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

    def rewrite_query(self, question: str, history: list[tuple[str, str]]) -> str:
        """후속 질문을 검색(임베딩+FTS)용 독립 질문으로 다시 쓴다.

        "그건 언제야?" 처럼 대명사만 남은 후속 질문은 원문 그대로 벡터화/FTS하면 이전 대화의
        실제 주제를 못 잡아 검색이 빗나간다 — history 를 보고 대명사를 구체적인 표현으로
        채운 독립 질문을 만들어 검색에만 쓴다(답변 생성 프롬프트는 원래 질문 그대로 받는다,
        거긴 이미 history 블록이 따로 들어가 GPT가 직접 문맥을 볼 수 있어서다).
        호출부는 history 가 비어 있을 때(새 대화의 첫 질문) 이 메서드를 부르지 않는다.
        """
        ...

    def answer_with_context(
        self,
        question: str,
        contexts: list[RagContext],
        history: list[tuple[str, str]] | None = None,
    ) -> RagAnswer:
        """검색된 근거(contexts)만 사용해 질문에 답한다.

        history 는 이전 턴의 (질문, 답변) 목록 — 후속 질문("그건 왜?")을 위해 오래된 순으로 넣는다.
        근거에 답이 없으면 모른다고 답해야 한다(없는 내용을 만들지 않는다).
        """
        ...

    def answer_with_context_stream(
        self,
        question: str,
        contexts: list[RagContext],
        history: list[tuple[str, str]] | None = None,
    ) -> Iterable[str]:
        """answer_with_context 와 같은 근거 규칙으로 답변을 델타(토큰 조각) 단위로 흘려보낸다.

        JSON 래퍼 없이 순수 텍스트만 낸다 — 스트리밍 중에는 완결된 JSON을 받을 수 없어
        answer_with_context 의 citations 필드 방식을 그대로 쓸 수 없다. 대신 텍스트에 이미
        박히는 [n] 표기를 스트림 종료 후 `extract_cited_indexes` 로 추출한다.
        구현체는 설정 문제(API 키 없음 등)를 이 메서드 호출 시점에 바로 raise 해야 한다
        (반환값을 순회하기 시작할 때가 아니라) — 호출부가 스트림을 열기 전에 404/503으로
        끊을 수 있는 건 이 타이밍뿐이다.
        """
        ...

    def generate_quiz(
        self,
        contexts: list[RagContext],
        *,
        count: int,
        types: list[str],
        difficulty: str | None = None,
        avoid_texts: list[str] | None = None,
    ) -> list[QuizDraft]:
        """근거(contexts)만 사용해 문항 count 개를 만든다.

        types 는 허용 문항 유형, difficulty 가 None 이면 난이도를 섞는다.
        avoid_texts 는 이미 출제된 문항 본문 — 같은 문제를 다시 만들지 않게 하는 힌트다.
        반환은 검증 전 초안이며, 개수가 count 와 정확히 같지 않을 수 있다.
        """
        ...


_CITATION_RE = re.compile(r"\[(\d+)\]")


def extract_cited_indexes(text: str, valid_indexes: set[int]) -> list[int]:
    """스트리밍 답변 본문에서 [n] 표기를 등장 순서대로 뽑는다(중복 제거).

    valid_indexes 밖의 번호는 모델이 만들어 낸 것(환각)이거나 각주가 아닌 다른 용도의
    대괄호이므로 버린다 — answer_with_context 의 JSON citations 필터링과 같은 방어.
    """
    cited: list[int] = []
    for match in _CITATION_RE.finditer(text):
        idx = int(match.group(1))
        if idx in valid_indexes and idx not in cited:
            cited.append(idx)
    return cited


CONFIDENCE_MARKER_RE = re.compile(r"\n?\[\[CONF:([01](?:\.\d{1,2})?)\]\]\s*$")


def strip_confidence_marker(text: str) -> tuple[str, float | None]:
    """텍스트 끝의 `[[CONF:0.xx]]` 마커를 떼어내고 (본문, confidence)를 돌려준다"""
    match = CONFIDENCE_MARKER_RE.search(text)
    if not match:
        return text, None
    value = min(1.0, max(0.0, float(match.group(1))))
    return text[: match.start()].rstrip(), value
