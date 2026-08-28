from __future__ import annotations

import re
from collections.abc import Iterable

from app.services.llm.base import EssayGrade, ProofreadFinding, QuizDraft, RagAnswer, RagContext

# 키 없이도 데모가 되도록 하는 아주 단순한 규칙 사전
# 실제 교정은 OpenAILLMProvider(GPT)가 담당하고 이건 개발/폴백용
_COMMON_TYPOS: dict[str, tuple[str, str]] = {
    "됬": ("됐", "'되었'의 준말은 '됐'입니다"),
    "안되요": ("안돼요", "'되어요'의 준말이므로 '안돼요'가 맞습니다"),
    "안됀": ("안 된", "'안 된'으로 띄어 씁니다"),
    "왠만": ("웬만", "'웬만하다'가 표준어입니다"),
    "역활": ("역할", "'역할'이 올바른 표기입니다"),
    "몇일": ("며칠", "'며칠'이 올바른 표기입니다"),
    "바램": ("바람", "'바라다'의 명사형은 '바람'입니다"),
    "설레임": ("설렘", "'설레다'의 명사형은 '설렘'입니다"),
    "금새": ("금세", "'지금 바로'의 뜻은 '금세'입니다"),
    "일찌기": ("일찍이", "'일찍이'가 올바른 표기입니다"),
    "오랫만": ("오랜만", "'오래간만'의 준말은 '오랜만'입니다"),
    "어의없": ("어이없", "'어이없다'가 올바른 표기입니다"),
    "희안": ("희한", "'희한하다'가 올바른 표기입니다"),
}

_MULTISPACE = re.compile(r"[^\S\n]{2,}")


class MockLLMProvider:
    """규칙 기반 오탈자 검출기(개발/폴백용, API 키 불필요)."""

    name = "mock"

    def proofread(self, text: str) -> list[ProofreadFinding]:
        findings: list[ProofreadFinding] = []
        seen: set[str] = set()

        for typo, (fix, reason) in _COMMON_TYPOS.items():
            if typo in text and typo not in seen:
                seen.add(typo)
                findings.append(
                    ProofreadFinding(
                        original=typo,
                        suggestion=fix,
                        reason=reason,
                        category="spelling",
                    )
                )

        # 연속 공백(줄바꿈 제외)
        if _MULTISPACE.search(text):
            findings.append(
                ProofreadFinding(
                    original="  ",
                    suggestion=" ",
                    reason="연속된 공백은 하나로 줄입니다",
                    category="spacing",
                )
            )
        return findings

    def proofread_batch(self, texts: list[str]) -> list[list[ProofreadFinding]]:
        # 규칙 기반은 호출 비용이 없으므로 각 텍스트를 그대로 처리한다.
        return [self.proofread(t) for t in texts]

    def rewrite_query(self, question: str, history: list[tuple[str, str]]) -> str:
        """실제 재작성은 GPT의 몫이므로 흉내내지 않고 원문 그대로 돌려준다(배선확인용)"""
        return question

    def answer_with_context(
        self,
        question: str,
        contexts: list[RagContext],
        history: list[tuple[str, str]] | None = None,
    ) -> RagAnswer:
        """키 없이 RAG 배선을 확인할 수 있게 검색된 1순위 근거를 그대로 요약"""
        if not contexts:
            return RagAnswer(
                answer="제공된 문서에서는 확인할 수 없습니다. (mock provider — 검색 결과 없음)",
                cited_indexes=[],
                confidence=0.0,
            )
        top = contexts[0]
        excerpt = top.content if len(top.content) <= 300 else top.content[:300] + "…"
        return RagAnswer(
            answer=(
                f"[mock provider] 질문 「{question}」에 대해 검색된 1순위 근거는 "
                f"{top.label} 입니다.\n\n{excerpt} [{top.index}]\n\n"
                "실제 자연어 답변은 OPENAI_API_KEY 를 설정하면 GPT가 생성합니다."
            ),
            cited_indexes=[top.index],
            confidence=0.75,
        )

    def answer_with_context_stream(
        self,
        question: str,
        contexts: list[RagContext],
        history: list[tuple[str, str]] | None = None,
    ) -> Iterable[str]:
        """실제 provider와 배선을 맞추려고 완성된 답을 단어 단위로 흉내만 내서 흘려보낸다."""
        answer = self.answer_with_context(question, contexts, history)
        confidence = answer.confidence if answer.confidence is not None else 0.0
        text = f"{answer.answer}\n[[CONF:{confidence:.2f}]]"
        return self._split_words(text)

    @staticmethod
    def _split_words(text: str) -> Iterable[str]:
        words = text.split(" ")
        for i, word in enumerate(words):
            yield word if i == len(words) - 1 else word + " "

    def generate_quiz(
        self,
        contexts: list[RagContext],
        *,
        count: int,
        types: list[str],
        difficulty: str | None = None,
        avoid_texts: list[str] | None = None,
    ) -> list[QuizDraft]:
        """키 없이 생성 배선(배치 분할 -> 검증 -> 문항 저장)을 확인하기 위한 캔드 문항"""
        if not contexts or count <= 0:
            return []

        allowed = [
            t for t in ("SINGLE_CHOICE", "TRUE_FALSE", "SHORT_ANSWER", "ESSAY") if t in set(types)
        ]
        allowed = allowed or ["SINGLE_CHOICE"]
        # avoid_texts 는 일부러 무시한다

        drafts: list[QuizDraft] = []
        for i in range(count):
            ctx = contexts[i % len(contexts)]
            qtype = allowed[i % len(allowed)]
            snippet = ctx.content.strip().replace("\n", " ")[:60] or "(근거 없음)"
            text = f"[mock] {ctx.label} 근거[{ctx.index}]의 내용에 관한 문항 {i + 1}: 「{snippet}」"

            if qtype == "SINGLE_CHOICE":
                draft = QuizDraft(
                    type=qtype,
                    text=text,
                    options=["보기 1(정답)", "보기 2", "보기 3", "보기 4"],
                    correct_answer="0",
                    explanation=f"mock provider 가 근거[{ctx.index}]로 만든 예시 해설입니다.",
                    difficulty=difficulty or "MEDIUM",
                    tags=["mock"],
                    source_index=ctx.index,
                )
            elif qtype == "TRUE_FALSE":
                draft = QuizDraft(
                    type=qtype,
                    text=text,
                    correct_answer="O",
                    explanation=f"mock provider 가 근거[{ctx.index}]로 만든 예시 해설입니다.",
                    difficulty=difficulty or "MEDIUM",
                    tags=["mock"],
                    source_index=ctx.index,
                )
            else:
                draft = QuizDraft(
                    type=qtype,
                    text=text,
                    correct_answer="mock",
                    explanation=f"mock provider 가 근거[{ctx.index}]로 만든 예시 해설입니다.",
                    difficulty=difficulty or "MEDIUM",
                    tags=["mock"],
                    source_index=ctx.index,
                )
            drafts.append(draft)
        return drafts

    def grade_essay(
        self, *, question: str, model_answer: str, rubric: str, user_answer: str
    ) -> EssayGrade:
        """실제 채점은 GPT의 몫이므로 흉내내지 않고 모범답안과의 단어 겹침 비율로 대충 점수만"""
        model_words = set(model_answer.split())
        given_words = set((user_answer or "").split())
        if not model_words or not given_words:
            score = 0.0
        else:
            score = round(len(model_words & given_words) / len(model_words) * 100, 1)
        return EssayGrade(
            score=score,
            feedback=(
                f"[mock provider] 모범답안과 겹치는 단어 비율로 매긴 임시 점수입니다({score}점). "
                "실제 채점은 OPENAI_API_KEY 를 설정하면 GPT가 수행합니다."
            ),
        )

    def judge_short_answer(self, *, question: str, correct_answer: str, user_answer: str) -> bool:
        """실제 판정은 GPT의 몫이므로 흉내내지 않고 단어 겹침 비율이 절반 이상이면 정답으로"""
        correct_words = set(correct_answer.split())
        given_words = set((user_answer or "").split())
        if not correct_words or not given_words:
            return False
        return len(correct_words & given_words) / len(correct_words) >= 0.5
