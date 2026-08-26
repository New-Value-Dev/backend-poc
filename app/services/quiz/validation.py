"""LLM 초안(QuizDraft) 검증 — 그대로 DB 행이 되므로 반드시 통과"""

from __future__ import annotations

import re

from app.models.quiz_question import (
    DIFFICULTY_MEDIUM,
    QUESTION_TYPE_SHORT_ANSWER,
    QUESTION_TYPE_SINGLE_CHOICE,
    QUESTION_TYPE_TRUE_FALSE,
    QUIZ_DIFFICULTIES,
)
from app.services.llm.base import QuizDraft

_WHITESPACE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """중복 비교용 정규화 — 공백 축약 + 소문자."""
    return _WHITESPACE.sub(" ", (text or "").strip()).lower()


def validate_draft(
    draft: QuizDraft,
    *,
    allowed_types: set[str],
    requested_difficulty: str | None = None,
) -> tuple[QuizDraft | None, str | None]:
    """(정제된 초안, None) 또는 (None, 버린 이유)."""
    if draft.type not in allowed_types:
        return None, f"요청하지 않은 유형({draft.type or '없음'})"

    text = (draft.text or "").strip()
    if not text:
        return None, "문제 본문 없음"

    explanation = (draft.explanation or "").strip()
    if not explanation:
        # DB NOT NULL 이고, 해설 없는 문항은 오답노트에서 쓸모가 없다.
        return None, "해설 없음"

    answer = (draft.correct_answer or "").strip()
    options: list[str] | None = None

    if draft.type == QUESTION_TYPE_SINGLE_CHOICE:
        raw = [o.strip() for o in (draft.options or []) if o and o.strip()]
        if len(raw) < 2:
            return None, f"객관식 선택지가 {len(raw)}개"
        try:
            idx = int(answer)
        except ValueError:
            return None, f"객관식 정답이 인덱스가 아님({answer!r})"
        if not 0 <= idx < len(raw):
            return None, f"객관식 정답 인덱스 범위 밖({idx}/{len(raw)})"
        options = raw
        answer = str(idx)

    elif draft.type == QUESTION_TYPE_TRUE_FALSE:
        upper = answer.upper()
        # 모델이 O/X 대신 true/false, 예/아니오로 답하는 경우가 흔해 받아 준다.
        mapping = {
            "O": "O", "X": "X",
            "TRUE": "O", "FALSE": "X",
            "예": "O", "아니오": "X", "아니요": "X",
            "참": "O", "거짓": "X",
        }
        if upper not in mapping and answer not in mapping:
            return None, f"O/X 정답 표기가 아님({answer!r})"
        answer = mapping.get(upper) or mapping[answer]

    elif draft.type == QUESTION_TYPE_SHORT_ANSWER:
        if not answer:
            return None, "단답형 정답 없음"

    difficulty = (draft.difficulty or "").strip().upper()
    if difficulty not in QUIZ_DIFFICULTIES:
        difficulty = (requested_difficulty or DIFFICULTY_MEDIUM).upper()
        if difficulty not in QUIZ_DIFFICULTIES:
            difficulty = DIFFICULTY_MEDIUM

    return (
        QuizDraft(
            type=draft.type,
            text=text,
            correct_answer=answer,
            explanation=explanation,
            options=options,
            difficulty=difficulty,
            tags=[t.strip() for t in (draft.tags or []) if t and t.strip()],
            source_index=draft.source_index,
        ),
        None,
    )
