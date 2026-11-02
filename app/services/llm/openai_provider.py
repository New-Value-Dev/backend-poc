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
from app.services.llm.finding_filter import parse_finding
from app.services.llm.prompts import (
    DEFAULT_REASONS,
    ESSAY_GRADING_SYSTEM,
    QUERY_REWRITE_SYSTEM,
    RAG_SYSTEM,
    RAG_SYSTEM_STREAM,
    SHORT_ANSWER_JUDGE_SYSTEM,
    active_categories,
    essay_grading_user_message,
    proofread_output_format,
    proofread_prompt,
    query_rewrite_user_message,
    quiz_system,
    quiz_user_message,
    rag_user_message,
    short_answer_judge_user_message,
)

logger = logging.getLogger(__name__)

_PROOFREAD_EFFORT_CHOICES = ("auto", "none", "low")
# 추론 토큰도 max_output_tokens 에 포함되므로 추론을 켜면 JSON 출력 몫과 별도로 여유를 둔다.
_PROOFREAD_REASONING_TOKEN_HEADROOM = 6000
_PROOFREAD_MAX_OUTPUT_TOKENS = 16000
_PROOFREAD_NO_REASONING_MAX_OUTPUT_TOKENS = 8000
# reasoning 파라미터를 받는 모델 계열(gpt-4o 등은 보내면 400)
_REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")


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
        proofread_reasoning_effort: str = "auto",
        proper_nouns: Iterable[str] = (),
        on_usage: Callable[[LLMUsageEvent], None] | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._reasoning_effort = reasoning_effort
        self._on_usage = on_usage
        self.name = f"openai:{model}"

        self._categories = active_categories(categories)
        self._allowed = set(self._categories)
        self._proper_nouns = [p.strip() for p in proper_nouns if p and p.strip()]

        effort_setting = (proofread_reasoning_effort or "auto").strip().lower()
        if effort_setting not in _PROOFREAD_EFFORT_CHOICES:
            logger.warning(
                "PROOFREAD_REASONING_EFFORT=%r 는 지원하지 않는 값이라 auto 를 사용한다 (허용: %s)",
                proofread_reasoning_effort,
                ", ".join(_PROOFREAD_EFFORT_CHOICES),
            )
            effort_setting = "auto"
        if effort_setting == "auto":
            # 맞춤법·띄어쓰기는 기계적으로 판정되는 항목이라 추론을 켜도 정확도는 그대로고
            # 느려지기만 한다(실측). 문맥 판단이 필요한 문법·표현이 켜져 있을 때만 low 를 쓴다.
            effort_setting = (
                "low"
                if any(c in ("grammar", "expression") for c in self._categories)
                else "none"
            )
        self._proofread_effort = effort_setting

    def proofread(self, text: str) -> list[ProofreadFinding]:
        return self.proofread_batch([text])[0]

    def proofread_batch(self, texts: list[str]) -> list[list[ProofreadFinding]]:
        if not texts:
            return []

        prompt = proofread_prompt(texts, self._categories, self._proper_nouns)
        data = self._load_json(
            self._responses(
                prompt,
                max_output_tokens=self._proofread_max_output_tokens(texts),
                text_format=proofread_output_format(len(texts), self._categories),
                feature="proofread_batch",
            )
        )

        raw_results = data.get("results")
        if not isinstance(raw_results, list) or len(raw_results) != len(texts):
            got = len(raw_results) if isinstance(raw_results, list) else "N/A"
            raise LLMError(
                f"교정 응답의 results 개수가 입력과 다릅니다 (기대 {len(texts)}개, 응답 {got}개)"
            )

        out: list[list[ProofreadFinding]] = [[] for _ in texts]
        seen: set[int] = set()
        for item in raw_results:
            idx = item.get("index") if isinstance(item, dict) else None
            if type(idx) is not int or not (0 <= idx < len(texts)) or idx in seen:
                raise LLMError("교정 응답의 index 가 잘못되었거나 중복되었습니다")
            seen.add(idx)
            raw_findings = item.get("findings")
            if not isinstance(raw_findings, list):
                raise LLMError("교정 응답의 findings 가 배열이 아닙니다")
            out[idx] = self._to_findings(raw_findings, texts[idx])
        return out

    def _proofread_max_output_tokens(self, texts: list[str]) -> int:
        # 카테고리가 늘수록 지적도 늘어난다(기본 2개 카테고리 기준으로 비례)
        category_factor = len(self._categories) / 2
        base_tokens = max(800, sum(len(t) for t in texts) // 2 + 500)
        if self._proofread_effort == "none" or not self._supports_reasoning():
            cap, headroom = _PROOFREAD_NO_REASONING_MAX_OUTPUT_TOKENS, 0
        else:
            cap, headroom = (
                _PROOFREAD_MAX_OUTPUT_TOKENS,
                _PROOFREAD_REASONING_TOKEN_HEADROOM,
            )
        return min(cap, int(base_tokens * category_factor) + headroom)

    def _supports_reasoning(self) -> bool:
        return self._model.lower().startswith(_REASONING_MODEL_PREFIXES)

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

    def _responses(
        self,
        prompt: str,
        *,
        max_output_tokens: int,
        text_format: dict,
        feature: str,
    ) -> str:
        """Responses API 로 strict json_schema 응답을 받아 output_text 를 돌려준다"""
        if not self._api_key:
            raise LLMConfigError("OPENAI_API_KEY 가 설정되지 않았습니다")
        payload: dict = {
            "model": self._model,
            "input": [
                {"role": "user", "content": [{"type": "input_text", "text": prompt}]}
            ],
            "max_output_tokens": max_output_tokens,
            "text": {"format": text_format},
        }
        # 추론을 끈 호출(또는 추론 미지원 모델)은 temperature 0 으로 결과를 고정한다.
        # 추론 모드에서는 temperature 를 지정할 수 없다.
        if self._supports_reasoning():
            payload["reasoning"] = {"effort": self._proofread_effort}
            if self._proofread_effort == "none":
                payload["temperature"] = 0
        else:
            payload["temperature"] = 0

        started = time.perf_counter()
        try:
            resp = httpx.post(
                f"{self._base_url}/responses",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            body = resp.json()
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
        except (httpx.HTTPError, ValueError) as exc:
            self._emit_usage(
                feature=feature,
                status="fail",
                latency_ms=(time.perf_counter() - started) * 1000,
                error_message=str(exc)[:500],
            )
            raise LLMError(f"OpenAI 호출 실패: {exc}") from exc

        usage = body.get("usage") or {}
        self._emit_usage(
            feature=feature,
            status="success",
            latency_ms=(time.perf_counter() - started) * 1000,
            usage={
                "prompt_tokens": usage.get("input_tokens"),
                "completion_tokens": usage.get("output_tokens"),
                "total_tokens": usage.get("total_tokens"),
            },
        )

        if body.get("status") != "completed":
            reason = (body.get("incomplete_details") or {}).get("reason")
            raise LLMError(
                f"교정 응답이 완료되지 않았습니다: {body.get('status')}"
                + (f" ({reason})" if reason else "")
            )
        parts: list[str] = []
        for output in body.get("output") or []:
            if output.get("type") != "message":
                continue
            for part in output.get("content") or []:
                if part.get("type") == "refusal":
                    raise LLMError("모델이 교정 요청에 대한 응답을 거절했습니다")
                if part.get("type") == "output_text":
                    parts.append(part.get("text", ""))
        return "".join(parts)

    def _to_findings(self, raw: list, source_text: str) -> list[ProofreadFinding]:
        """모델이 준 축약 finding(o/s/c/n)을 검증해 ProofreadFinding 으로 바꾼다.

        원문(source_text)에 실제로 없는 구절, 정상 표기를 건드린 제안, 허용 카테고리 밖 제안,
        고유명사를 건드린 제안은 버린다.
        """
        findings: list[dict] = []
        recovered: list[dict] = []
        dropped = 0
        for item in raw:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("o"), str)
                or not isinstance(item.get("s"), str)
                or not isinstance(item.get("c"), str)
                or type(item.get("n")) is not int
            ):
                raise LLMError("교정 응답의 finding 형식이 잘못되었습니다")
            parsed = parse_finding(item, self._allowed, self._proper_nouns)
            if parsed is None:
                dropped += 1
                continue
            count = source_text.count(parsed["original"])
            if count < parsed["occurrence"]:
                if count != 1:
                    # 일치 문구가 없거나 후보가 여러 개면 위치를 추측하지 않는다.
                    dropped += 1
                    continue
                # 등장 순서(n)만 틀리고 원문에 한 번만 있으면 그 위치로 보정한다.
                parsed["occurrence"] = 1
                recovered.append(parsed)
                continue
            findings.append(parsed)

        # 정상 좌표로 반환된 교정이 있으면 보정된 제안보다 우선한다.
        positions = {(f["original"], f["occurrence"]) for f in findings}
        for f in recovered:
            position = (f["original"], f["occurrence"])
            if position not in positions:
                findings.append(f)
                positions.add(position)

        if dropped:
            # 프롬프트로 막아도 새어 나오는 제안이 있다. 조용히 버리지 않고 남긴다.
            logger.info("교정 제안 %d건 제외 (허용: %s)", dropped, self._categories)
        return [
            ProofreadFinding(
                original=f["original"],
                suggestion=f["suggestion"],
                reason=DEFAULT_REASONS[f["category"]],
                category=f["category"],
                occurrence=f["occurrence"],
            )
            for f in findings
        ]
