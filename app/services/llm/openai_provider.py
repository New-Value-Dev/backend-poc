from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterable, Iterator, Sequence

import httpx

from app.services.llm.base import (
    EssayGrade,
    LLMConfigError,
    LLMError,
    LLMUsageEvent,
    ProofreadFinding,
    QuizDraft,
    RagAnswer,
    RagContext,
)
from app.services.llm.prompts import (
    ESSAY_GRADING_SYSTEM,
    KNOWN_CATEGORIES,
    QUERY_REWRITE_SYSTEM,
    RAG_SYSTEM,
    RAG_SYSTEM_STREAM,
    SHORT_ANSWER_JUDGE_SYSTEM,
    essay_grading_user_message,
    proofread_batch_system,
    proofread_system,
    query_rewrite_user_message,
    quiz_system,
    quiz_user_message,
    rag_user_message,
    short_answer_judge_user_message,
)

logger = logging.getLogger(__name__)


class OpenAILLMProvider:
    """OpenAI Chat Completions 로 교정하는 provider"""

    def __init__(
        self,
        api_key: str | None,
        *,
        model: str,
        base_url: str,
        categories: Iterable[str] = ("spelling", "spacing"),
        timeout: float = 120.0,
        reasoning_effort: str | None = None,
        on_usage: Callable[[LLMUsageEvent], None] | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._reasoning_effort = reasoning_effort
        self._on_usage = on_usage
        self.name = f"openai:{model}"

        self._categories = [c for c in KNOWN_CATEGORIES if c in set(categories)] or [
            "spelling"
        ]
        self._allowed = set(self._categories)
        self._system = proofread_system(self._categories)
        self._batch_system = proofread_batch_system(self._categories)

    def proofread(self, text: str) -> list[ProofreadFinding]:
        content = self._chat(self._system, text, feature="proofread")
        data = self._load_json(content)
        raw = data.get("findings", []) if isinstance(data, dict) else []
        return self._to_findings(raw)

    def proofread_batch(self, texts: list[str]) -> list[list[ProofreadFinding]]:
        if not texts:
            return []
        # [번호] 마커로 여러 조각을 한 요청에 담는다.
        user = "\n\n".join(f"[{i}] {t}" for i, t in enumerate(texts))
        content = self._chat(self._batch_system, user, feature="proofread_batch")
        data = self._load_json(content)

        out: list[list[ProofreadFinding]] = [[] for _ in texts]
        results = data.get("results", []) if isinstance(data, dict) else []
        for item in results:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            if not isinstance(idx, int) or not (0 <= idx < len(texts)):
                continue
            out[idx] = self._to_findings(item.get("findings", []))
        return out

    def rewrite_query(self, question: str, history: list[tuple[str, str]]) -> str:
        if not history:
            return question
        user = query_rewrite_user_message(question, history)
        rewritten = self._chat(
            QUERY_REWRITE_SYSTEM, user, json_mode=False, feature="rag_rewrite"
        ).strip()
        return rewritten or question

    def answer_with_context(
        self,
        question: str,
        contexts: list[RagContext],
        history: list[tuple[str, str]] | None = None,
    ) -> RagAnswer:
        user = rag_user_message(
            question,
            [(c.index, c.label, c.content) for c in contexts],
            history or [],
        )
        data = self._load_json(self._chat(RAG_SYSTEM, user, feature="rag_answer"))

        answer = str(data.get("answer", "")).strip()
        if not answer:
            raise LLMError("RAG 답변이 비어 있습니다")

        valid = {c.index for c in contexts}
        cited: list[int] = []
        for raw in data.get("citations", []) or []:
            # 모델이 "[1]"처럼 문자열로 주거나 없는 번호를 만들어 내는 경우가 있어 걸러낸다
            try:
                idx = int(str(raw).strip().strip("[]"))
            except ValueError:
                continue
            if idx in valid and idx not in cited:
                cited.append(idx)

        confidence = None
        raw_confidence = data.get("confidence")
        if isinstance(raw_confidence, (int, float)):
            confidence = min(1.0, max(0.0, float(raw_confidence)))
        return RagAnswer(answer=answer, cited_indexes=cited, confidence=confidence)

    def answer_with_context_stream(
        self,
        question: str,
        contexts: list[RagContext],
        history: list[tuple[str, str]] | None = None,
    ) -> Iterable[str]:
        # API 키 검증은 여기서 즉시(제너레이터를 만들기 전) 
        if not self._api_key:
            raise LLMConfigError("OPENAI_API_KEY 가 설정되지 않았습니다")
        user = rag_user_message(
            question,
            [(c.index, c.label, c.content) for c in contexts],
            history or [],
        )
        return self._chat_stream(RAG_SYSTEM_STREAM, user, feature="rag_answer_stream")

    def _chat_stream(self, system: str, user: str, *, feature: str) -> Iterator[str]:
        payload = {
            "model": self._model,
            "stream": True,
            "stream_options": {"include_usage": True},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if self._reasoning_effort:
            payload["reasoning_effort"] = self._reasoning_effort
        started = time.perf_counter()
        try:
            with httpx.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
                timeout=self._timeout,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    usage = obj.get("usage")
                    if usage:
                        self._emit_usage(
                            feature=feature,
                            status="success",
                            latency_ms=(time.perf_counter() - started) * 1000,
                            usage=usage,
                        )
                    choices = obj.get("choices") or []
                    delta = choices[0].get("delta", {}).get("content") if choices else None
                    if delta:
                        yield delta
        except httpx.HTTPStatusError as exc:
            exc.response.read()
            self._emit_usage(
                feature=feature,
                status="fail",
                latency_ms=(time.perf_counter() - started) * 1000,
                error_message=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
            )
            raise LLMError(
                f"OpenAI 응답 오류 {exc.response.status_code}: {exc.response.text[:200]}"
            ) from exc
        except httpx.HTTPError as exc:
            self._emit_usage(
                feature=feature,
                status="fail",
                latency_ms=(time.perf_counter() - started) * 1000,
                error_message=str(exc)[:500],
            )
            raise LLMError(f"OpenAI 호출 실패: {exc}") from exc

    def generate_quiz(
        self,
        contexts: list[RagContext],
        *,
        count: int,
        types: list[str],
        difficulty: str | None = None,
        avoid_texts: list[str] | None = None,
    ) -> list[QuizDraft]:
        if not contexts or count <= 0:
            return []

        system = quiz_system(types, difficulty)
        user = quiz_user_message(
            [(c.index, c.label, c.content) for c in contexts],
            count=count,
            avoid_texts=avoid_texts or [],
        )
        data = self._load_json(self._chat(system, user, feature="quiz_generate"))

        raw = data.get("questions", [])
        if not isinstance(raw, list):
            return []

        valid_indexes = {c.index for c in contexts}
        drafts: list[QuizDraft] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue

            options = item.get("options")
            if isinstance(options, list):
                options = [str(o).strip() for o in options if str(o).strip()]
            else:
                options = None

            tags = item.get("tags")
            tags = (
                [str(t).strip() for t in tags if str(t).strip()]
                if isinstance(tags, list)
                else []
            )

            # answer_with_context 와 같은 환각 방어 -> 없는 근거 번호를 만들어 내면 출처를 버림
            source_index = None
            try:
                candidate = int(str(item.get("source_index", "")).strip().strip("[]"))
            except ValueError:
                candidate = None
            if candidate in valid_indexes:
                source_index = candidate

            drafts.append(
                QuizDraft(
                    type=str(item.get("type", "")).strip().upper(),
                    text=text,
                    correct_answer=str(item.get("correct_answer", "")).strip(),
                    explanation=str(item.get("explanation", "")).strip(),
                    options=options,
                    difficulty=str(item.get("difficulty", "")).strip().upper() or "MEDIUM",
                    tags=tags,
                    source_index=source_index,
                )
            )
        return drafts

    def grade_essay(
        self, *, question: str, model_answer: str, rubric: str, user_answer: str
    ) -> EssayGrade:
        user = essay_grading_user_message(
            question=question, model_answer=model_answer, rubric=rubric, user_answer=user_answer
        )
        data = self._load_json(
            self._chat(ESSAY_GRADING_SYSTEM, user, feature="quiz_grade_essay")
        )

        raw_score = data.get("score")
        try:
            score = min(100.0, max(0.0, float(raw_score)))
        except (TypeError, ValueError):
            raise LLMError(f"서술형 채점 응답의 score 가 숫자가 아닙니다: {raw_score!r}") from None
        feedback = str(data.get("feedback", "")).strip()
        return EssayGrade(score=score, feedback=feedback)

    def judge_short_answer(self, *, question: str, correct_answer: str, user_answer: str) -> bool:
        user = short_answer_judge_user_message(
            question=question, correct_answer=correct_answer, user_answer=user_answer
        )
        data = self._load_json(
            self._chat(SHORT_ANSWER_JUDGE_SYSTEM, user, feature="quiz_grade_short_answer")
        )
        raw = data.get("correct")
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() == "true"

    # ── 내부 ──

    def _chat(self, system: str, user: str, *, feature: str, json_mode: bool = True) -> str:
        if not self._api_key:
            raise LLMConfigError("OPENAI_API_KEY 가 설정되지 않았습니다")
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self._reasoning_effort:
            payload["reasoning_effort"] = self._reasoning_effort
        started = time.perf_counter()
        try:
            resp = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            body = resp.json()
            self._emit_usage(
                feature=feature,
                status="success",
                latency_ms=(time.perf_counter() - started) * 1000,
                usage=body.get("usage"),
            )
            return body["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            self._emit_usage(
                feature=feature,
                status="fail",
                latency_ms=(time.perf_counter() - started) * 1000,
                error_message=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
            )
            raise LLMError(
                f"OpenAI 응답 오류 {exc.response.status_code}: {exc.response.text[:200]}"
            ) from exc
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            self._emit_usage(
                feature=feature,
                status="fail",
                latency_ms=(time.perf_counter() - started) * 1000,
                error_message=str(exc)[:500],
            )
            raise LLMError(f"OpenAI 호출 실패: {exc}") from exc

    def _emit_usage(
        self,
        *,
        feature: str,
        status: str,
        latency_ms: float,
        usage: dict | None = None,
        error_message: str | None = None,
    ) -> None:
        """계측 콜백 호출"""
        if not self._on_usage:
            return
        try:
            self._on_usage(
                LLMUsageEvent(
                    feature=feature,
                    model=self._model,
                    status=status,
                    prompt_tokens=(usage or {}).get("prompt_tokens"),
                    completion_tokens=(usage or {}).get("completion_tokens"),
                    total_tokens=(usage or {}).get("total_tokens"),
                    latency_ms=round(latency_ms, 1),
                    error_message=error_message,
                )
            )
        except Exception:
            logger.exception("LLM usage 콜백 실행 실패 (feature=%s)", feature)

    @staticmethod
    def _load_json(content: str) -> dict:
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"OpenAI 응답 JSON 파싱 실패: {exc}") from exc
        return data if isinstance(data, dict) else {}

    def _to_findings(self, raw) -> list[ProofreadFinding]:
        findings: list[ProofreadFinding] = []
        if not isinstance(raw, list):
            return findings
        dropped = 0
        for item in raw:
            if not isinstance(item, dict):
                continue
            original = str(item.get("original", "")).strip()
            if not original:
                continue
            category = self._normalize_category(item.get("category"))
            if category is None:
                dropped += 1
                continue
            findings.append(
                ProofreadFinding(
                    original=original,
                    suggestion=str(item.get("suggestion", "")).strip(),
                    reason=str(item.get("reason", "")).strip(),
                    category=category,
                )
            )
        if dropped:
            # 프롬프트로 막아도 긴 문서에서는 종종 새어 나온다. 조용히 버리지 않고 남긴다.
            logger.info("검사 범위 밖 지적 %d건 제외 (허용: %s)", dropped, self._categories)
        return findings

    def _normalize_category(self, raw) -> str | None:
        """응답의 category 를 허용 목록에 맞춘다. 제외 대상이면 None"""
        category = str(raw or "").strip().lower()
        if category in self._allowed:
            return category
        if category in KNOWN_CATEGORIES:
            return None
        return self._categories[0]
