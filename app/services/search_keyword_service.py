"""RAG 챗봇 질문에서 자주 등장하는 키워드(명사) 순위 — 관리자 전용"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from sqlalchemy.orm import Session

from app.repositories.rag_repository import RagMessageRepository

_NOUN_TAGS = {"NNG", "NNP"}
_MIN_LEN = 2
# 질문에 거의 항상 섞여 나와 순위를 오염시키는 일반어
_STOPWORDS = {"질문", "문서", "내용", "확인", "사용", "관련", "정보"}

_kiwi = None


def _get_kiwi():
    """Kiwi 는 초기화 비용이 있어 프로세스당 한 번만 만든다"""
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi

        _kiwi = Kiwi()
    return _kiwi


def extract_nouns(text: str) -> list[str]:
    kiwi = _get_kiwi()
    nouns = []
    for token in kiwi.tokenize(text):
        if (
            token.tag in _NOUN_TAGS
            and len(token.form) >= _MIN_LEN
            and token.form not in _STOPWORDS
        ):
            nouns.append(token.form)
    return nouns


def top_keywords(
    db: Session, *, start: datetime, end: datetime, limit: int = 20
) -> list[tuple[str, int]]:
    questions = RagMessageRepository(db).list_question_texts_between(start, end)
    counter: Counter[str] = Counter()
    for content in questions:
        counter.update(extract_nouns(content))
    return counter.most_common(limit)
