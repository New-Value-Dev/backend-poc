"""LLM 프롬프트 모음"""

from __future__ import annotations

from collections.abc import Iterable

# ── Proofread ──
KNOWN_CATEGORIES = ("spelling", "spacing", "grammar", "expression")

CATEGORY_LABELS = {
    "spelling": "맞춤법·오탈자",
    "spacing": "띄어쓰기",
    "grammar": "문법(조사·어미·호응)",
    "expression": "어색한 표현·문체",
}

_EXCLUSION_RULES = {
    "expression": (
        "- 문장이 어색하다 / 더 자연스럽게 / 간결하게 같은 표현·문체 제안\n"
        "- 문맥·논리·구성·어투에 대한 의견, 번역투 지적, 용어 통일 제안"
    ),
    "grammar": (
        "- 조사·어미·문장 호응 등 문법 지적 "
        "(단어 자체가 틀린 맞춤법이면 그건 맞춤법으로 본다)"
    ),
    "spacing": "- 띄어쓰기 지적",
    "spelling": "- 맞춤법·오탈자 지적",
}


def _scope(categories: Iterable[str]) -> tuple[str, str, str]:
    """(검사 대상 문구, 제외 규칙 블록, category enum 문구)."""
    active = [c for c in KNOWN_CATEGORIES if c in set(categories)] or ["spelling"]
    target = "·".join(CATEGORY_LABELS[c] for c in active)
    enum = "|".join(active)

    excluded = [c for c in KNOWN_CATEGORIES if c not in active]
    if excluded:
        rules = "\n".join(_EXCLUSION_RULES[c] for c in excluded)
        block = (
            "\n다음은 오류가 아니므로 **절대 지적하지 않는다**:\n"
            f"{rules}\n"
            "확신이 서지 않으면 지적하지 않는다. 명백히 틀린 것만 올린다.\n"
        )
    else:
        block = ""
    return target, block, enum


def proofread_system(categories: Iterable[str]) -> str:
    """단건 교정용 system 프롬프트. user 메시지는 검사할 텍스트."""
    target, exclusions, enum = _scope(categories)
    return (
        f"너는 한국어 문서 교정 전문가다. 입력 텍스트에서 {target} 오류만 찾아 교정한다. "
        "내용을 바꾸거나 새로 쓰지 말고, 실제 오류만 지적한다.\n"
        f"{exclusions}"
        "반드시 다음 형태의 JSON 객체 하나만 출력한다(설명 문장 금지):\n"
        '{"findings": [{"original": "원문 표현", "suggestion": "교정안", '
        f'"reason": "간단한 이유", "category": "{enum}"}}]}}\n'
        "오류가 없으면 findings 를 빈 배열로 둔다."
    )


# ── RAG ──

RAG_SYSTEM = (
    "너는 사내 문서 기반 질의응답 어시스턴트다. 사용자의 질문에 대해 **주어진 근거 문서 조각만**"
    " 사용해 한국어로 답한다.\n"
    "규칙:\n"
    "- 근거에 없는 내용은 절대 만들지 않는다. 근거가 부족하면 "
    '"제공된 문서에서는 확인할 수 없습니다"라고 답하고, 무엇이 없는지 짧게 덧붙인다.\n'
    "- 사용한 근거의 번호를 답변 문장 끝에 [1], [2] 형태로 표기한다. 여러 개면 [1][3]처럼 붙인다.\n"
    "- 근거를 그대로 복사하지 말고 질문에 맞게 정리해서 설명한다. 표·목록 형태의 근거는"
    " 필요한 항목만 골라 문장으로 풀어 준다.\n"
    "- 근거끼리 내용이 어긋나면 어느 문서가 무엇을 말하는지 구분해서 알려 준다.\n"
    "- 추측·일반 상식으로 메우지 않는다. 문서 밖 지식을 덧붙이지 않는다.\n"
    "- confidence 에는 이 답변이 근거로 얼마나 뒷받침되는지 0.0~1.0 사이 값을 스스로 매긴다."
    " 근거에 명확히 있으면 높게, 일부만 있거나 여러 근거를 짜맞춘 경우 중간, 근거가 부족해"
    ' "확인할 수 없습니다"로 답한 경우 낮게(0.2 이하) 매긴다.\n'
    "반드시 다음 형태의 JSON 객체 하나만 출력한다(설명 문장 금지):\n"
    '{"answer": "답변 본문(마크다운 허용)", "citations": [사용한 근거 번호들], '
    '"confidence": 0.0~1.0}\n'
    "근거로 답할 수 없으면 answer 에 그 사실을 쓰고 citations 는 빈 배열로 둔다."
)


QUERY_REWRITE_SYSTEM = (
    "너는 검색엔진에 넣을 질문을 다시 쓰는 도우미다. 이전 대화와 후속 질문이 주어지면, "
    "후속 질문을 이전 대화 없이도 무슨 뜻인지 알 수 있는 독립적인 질문 하나로 다시 쓴다.\n"
    "규칙:\n"
    "- 후속 질문의 대명사·생략된 주어/목적어(그건, 거기, 그때, 그거 등)를 이전 대화에 나온 "
    "구체적인 표현으로 채운다.\n"
    "- 이전 대화나 후속 질문에 없는 새로운 사실이나 추측을 추가하지 않는다.\n"
    "- 후속 질문이 이미 이전 대화와 무관한 새 주제면 그대로 돌려준다.\n"
    "- 질문 문장 하나만 출력한다. 설명, 따옴표, 번호 매기기, 그 외 다른 텍스트 없이 "
    "다시 쓴 질문 자체만 낸다."
)


def query_rewrite_user_message(question: str, history: Iterable[tuple[str, str]]) -> str:
    """질문 재작성 user 메시지. history 는 (질문, 답변) 오래된 순."""
    lines = [f"Q: {q}\nA: {a}" for q, a in history]
    return (
        "# 이전 대화\n"
        + "\n\n".join(lines)
        + f"\n\n# 후속 질문\n{question}\n\n# 다시 쓴 독립 질문 (이 아래에 질문 하나만)"
    )


RAG_SYSTEM_STREAM = (
    "너는 사내 문서 기반 질의응답 어시스턴트다. 사용자의 질문에 대해 **주어진 근거 문서 조각만**"
    " 사용해 한국어로 답한다.\n"
    "규칙:\n"
    "- 근거에 없는 내용은 절대 만들지 않는다. 근거가 부족하면 "
    '"제공된 문서에서는 확인할 수 없습니다"라고 답하고, 무엇이 없는지 짧게 덧붙인다.\n'
    "- 사용한 근거의 번호를 답변 문장 끝에 [1], [2] 형태로 표기한다. 여러 개면 [1][3]처럼 붙인다.\n"
    "- 근거를 그대로 복사하지 말고 질문에 맞게 정리해서 설명한다. 표·목록 형태의 근거는"
    " 필요한 항목만 골라 문장으로 풀어 준다.\n"
    "- 근거끼리 내용이 어긋나면 어느 문서가 무엇을 말하는지 구분해서 알려 준다.\n"
    "- 추측·일반 상식으로 메우지 않는다. 문서 밖 지식을 덧붙이지 않는다.\n"
    "답변 본문만 마크다운으로 바로 출력한다. JSON이나 다른 wrapper 없이 답변 텍스트만 낸다."
    " 설명 문구 없이 답변 자체로 바로 시작한다.\n"
    "답변을 모두 끝낸 다음, 반드시 마지막 줄에 다른 어떤 문자도 없이 "
    '"[[CONF:0.xx]]" 형식의 표기 하나만 추가한다(예: [[CONF:0.85]]). 0.xx 는 이 답변이'
    " 근거로 얼마나 뒷받침되는지 0.0~1.0 사이로 스스로 매긴 값이다 — 근거에 명확히 있으면"
    ' 높게, 근거가 부족해 "확인할 수 없습니다"로 답했으면 낮게(0.2 이하) 매긴다.'
    " 이 표기는 사용자에게 보이지 않고 시스템이 떼어내 쓰므로, 반드시 답변의 맨 마지막에"
    " 정확히 이 형식으로만 한 번 출력한다(답변 중간에는 절대 쓰지 않는다)."
)


def rag_user_message(
    question: str,
    contexts: Iterable[tuple[int, str, str]],
    history: Iterable[tuple[str, str]] = (),
) -> str:
    """RAG user 메시지 조립/ contexts 는 (번호, 출처라벨, 본문)"""
    parts: list[str] = []

    turns = list(history)
    if turns:
        lines = [f"Q: {q}\nA: {a}" for q, a in turns]
        parts.append(
            "# 이전 대화(맥락 파악용, 근거로 쓰지 말 것)\n" + "\n\n".join(lines)
        )

    blocks = [f"[{idx}] (출처: {label})\n{content}" for idx, label, content in contexts]
    parts.append(
        "# 근거 문서 조각\n" + ("\n\n".join(blocks) if blocks else "(검색 결과 없음)")
    )
    parts.append(f"# 질문\n{question}")
    return "\n\n".join(parts)


# ── Quiz ──

QUIZ_TYPE_LABELS = {
    "SINGLE_CHOICE": "4지선다(객관식)",
    "TRUE_FALSE": "O/X",
    "SHORT_ANSWER": "단답형",
    "ESSAY": "서술형(주관식 장문)",
}

QUIZ_DIFFICULTY_LABELS = {
    "EASY": "쉬움(근거에 그대로 적힌 사실 확인)",
    "MEDIUM": "보통(근거를 이해해야 풀림)",
    "HARD": "어려움(여러 조항을 종합하거나 예외를 구분해야 풀림)",
}


def quiz_system(types: Iterable[str], difficulty: str | None = None) -> str:
    """출제용 system 프롬프트. 근거 밖 지식으로 문제를 만들지 않게 막는 게 핵심이다."""
    active = [t for t in QUIZ_TYPE_LABELS if t in set(types)] or ["SINGLE_CHOICE"]
    type_desc = ", ".join(f"{t}({QUIZ_TYPE_LABELS[t]})" for t in active)
    type_enum = "|".join(active)

    if difficulty and difficulty in QUIZ_DIFFICULTY_LABELS:
        diff_rule = (
            f"- 모든 문항의 난이도는 {difficulty}"
            f" — {QUIZ_DIFFICULTY_LABELS[difficulty]} 로 맞춘다.\n"
        )
        diff_enum = difficulty
    else:
        diff_rule = "- 난이도를 EASY/MEDIUM/HARD 로 적절히 섞는다.\n"
        diff_enum = "EASY|MEDIUM|HARD"

    return (
        "너는 사내 문서로 사내 교육용 시험 문제를 만드는 출제 전문가다. "
        "**주어진 근거 문서 조각만** 사용해 한국어 문항을 만든다.\n"
        "규칙:\n"
        "- 근거에 없는 내용으로 문제나 오답 선택지를 만들지 않는다. 일반 상식으로 메우지 않는다.\n"
        f"- 허용 문항 유형: {type_desc}. 이 유형만 쓴다.\n"
        f"{diff_rule}"
        "- 각 문항은 서로 다른 내용을 다룬다. 같은 사실을 표현만 바꿔 반복하지 않는다.\n"
        "- 문제 본문만 읽고도 무엇을 묻는지 알 수 있게 쓴다"
        '("위 문서에 따르면" 같은 표현으로 근거를 가리키지 않는다).\n'
        "- explanation 에는 정답인 이유를 근거 내용에 기반해 1~2문장으로 쓴다. 비워 두지 않는다.\n"
        "- source_index 에는 그 문항의 근거가 된 조각 번호를 하나 적는다.\n"
        "- SINGLE_CHOICE: options 는 4개, 그럴듯한 오답을 포함하고, correct_answer 는 "
        '정답 선택지의 **인덱스 문자열**("0"~"3")로 쓴다.\n'
        '- TRUE_FALSE: options 는 생략하고 correct_answer 는 "O" 또는 "X" 로 쓴다.\n'
        "- SHORT_ANSWER: options 는 생략하고 correct_answer 는 짧은 정답 표현(한 단어~한 구절)으로 쓴다.\n"
        "- ESSAY: options 는 생략하고 correct_answer 는 모범답안(2~4문장)으로 쓴다. "
        "explanation 에는 채점 시 반드시 포함돼야 할 핵심 요소를 채점기준으로 쓴다.\n"
        "반드시 다음 형태의 JSON 객체 하나만 출력한다(설명 문장 금지):\n"
        '{"questions": [{"type": "' + type_enum + '", "text": "문제 본문", '
        '"options": ["...", "...", "...", "..."], "correct_answer": "0", '
        '"explanation": "정답 근거", "difficulty": "' + diff_enum + '", '
        '"tags": ["주제"], "source_index": 1}]}\n'
        "근거로 문제를 만들 수 없으면 questions 를 빈 배열로 둔다."
    )


def quiz_user_message(
    contexts: Iterable[tuple[int, str, str]],
    *,
    count: int,
    avoid_texts: Iterable[str] = (),
) -> str:
    """출제 user 메시지. contexts 는 (번호, 출처라벨, 본문)."""
    parts: list[str] = []

    blocks = [f"[{idx}] (출처: {label})\n{content}" for idx, label, content in contexts]
    parts.append(
        "# 근거 문서 조각\n" + ("\n\n".join(blocks) if blocks else "(근거 없음)")
    )

    avoid = [t.strip() for t in avoid_texts if t and t.strip()]
    if avoid:
        listed = "\n".join(f"- {t}" for t in avoid)
        parts.append(
            "# 이미 출제된 문제(중복 금지 — 아래와 같은 내용을 묻지 말 것)\n" + listed
        )

    parts.append(f"# 요구사항\n위 근거만 사용해 문항 {count}개를 만든다.")
    return "\n\n".join(parts)


ESSAY_GRADING_SYSTEM = (
    "너는 사내 교육용 서술형 문제를 채점하는 채점관이다. "
    "문제, 모범답안, 채점기준, 응시자 답안이 주어지면 응시자 답안이 모범답안/채점기준의 "
    "핵심 내용을 얼마나 담고 있는지만 근거로 0~100점을 매긴다.\n"
    "규칙:\n"
    "- 표현이 다르더라도 같은 의미면 감점하지 않는다(문장력·맞춤법은 채점하지 않는다).\n"
    "- 모범답안/채점기준에 없는 내용을 추가로 요구하거나, 그 반대로 근거 없이 후하게 주지 않는다.\n"
    "- 핵심 내용이 전혀 없으면 0점, 핵심을 정확히 다 담았으면 100점에 가깝게 준다.\n"
    "- feedback 은 응시자에게 보여줄 채점 코멘트다. 무엇이 맞았고 무엇이 빠졌는지 1~3문장으로 "
    "구체적으로 쓴다(단순히 '틀렸습니다' 금지).\n"
    "반드시 다음 형태의 JSON 객체 하나만 출력한다(설명 문장 금지):\n"
    '{"score": 0~100 사이 숫자, "feedback": "채점 코멘트"}'
)


def essay_grading_user_message(
    *, question: str, model_answer: str, rubric: str, user_answer: str
) -> str:
    """서술형 채점 user 메시지. rubric 은 문항의 explanation(정답 근거/채점기준) 필드를 재사용한다."""
    parts = [
        f"# 문제\n{question}",
        f"# 모범답안\n{model_answer}",
    ]
    if rubric and rubric.strip() != model_answer.strip():
        parts.append(f"# 채점기준\n{rubric}")
    parts.append(f"# 응시자 답안\n{user_answer or '(답안 없음)'}")
    return "\n\n".join(parts)


SHORT_ANSWER_JUDGE_SYSTEM = (
    "너는 사내 교육용 단답형 문제의 채점을 최종 판정하는 심사관이다. "
    "문제, 정답, 응시자 답안이 주어지면 응시자 답안이 정답과 사실상 같은 뜻인지 true/false 로만 "
    "판정한다.\n"
    "규칙:\n"
    "- 표현·어순·조사가 달라도 같은 사실을 가리키면 true (예: '1년 근속' ↔ '1년 이상 계속 근로한').\n"
    "- 숫자·기간·금액·대상 등 핵심 사실이 정답과 다르면(예: 1년 vs 3년) 반드시 false. "
    "표현이 비슷해 보여도 사실이 다르면 오답이다 — 이게 가장 중요한 규칙이다.\n"
    "- 정답의 핵심 요소 중 일부가 빠졌으면 false.\n"
    "반드시 다음 형태의 JSON 객체 하나만 출력한다(설명 문장 금지): "
    '{"correct": true 또는 false}'
)


def short_answer_judge_user_message(*, question: str, correct_answer: str, user_answer: str) -> str:
    return (
        f"# 문제\n{question}\n\n"
        f"# 정답\n{correct_answer}\n\n"
        f"# 응시자 답안\n{user_answer or '(답안 없음)'}"
    )


def proofread_batch_system(categories: Iterable[str]) -> str:
    """배치 교정용. 여러 섹션을 [번호]로 묶어 보내고 index 로 되매핑한다."""
    target, exclusions, enum = _scope(categories)
    return (
        "너는 한국어 문서 교정 전문가다. 여러 텍스트 조각이 각각 [번호] 형식으로 주어진다.\n"
        f"각 조각에서 {target} 오류만 찾아 교정한다. "
        "내용을 바꾸거나 새로 쓰지 말고, 실제 오류만 지적한다.\n"
        f"{exclusions}"
        "반드시 다음 형태의 JSON 객체 하나만 출력한다(설명 문장 금지):\n"
        '{"results": [{"index": 조각번호, "findings": [{"original": "원문 표현", '
        '"suggestion": "교정안", "reason": "간단한 이유", '
        f'"category": "{enum}"}}]}}]}}\n'
        "오류가 없는 조각은 findings 를 빈 배열로 두거나 생략한다."
    )
