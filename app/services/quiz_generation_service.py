"""퀴즈 AI 문제 생성 — 202 + 폴링"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal, get_db
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.quiz_generation_job import (
    QUIZ_GEN_STATUS_COMPLETED,
    QUIZ_GEN_STATUS_FAILED,
    QUIZ_GEN_STATUS_RUNNING,
    QuizGenerationJob,
)
from app.models.quiz_question import (
    GENERATION_TYPE_AI,
    REVIEW_STATUS_DRAFT,
    QuizQuestion,
)
from app.repositories.document_repository import (
    DocumentRepository,
    DocumentVersionRepository,
)
from app.repositories.quiz_book_repository import QuizBookRepository
from app.repositories.quiz_generation_job_repository import QuizGenerationJobRepository
from app.repositories.quiz_question_repository import QuizQuestionRepository
from app.repositories.quiz_session_repository import QuizSessionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.quiz import QuizGenerateRequest
from app.services.activity_service import (
    Action,
    ActivityService,
    activity_service_for,
    get_activity_service,
)
from app.services.llm import LLMError
from app.services.llm.factory import get_llm_provider
from app.services.notification_service import (
    NotificationType,
    notification_service_for,
)
from app.services.quiz.planner import GenerationBatch, NoChunksError, plan_batches
from app.services.quiz.validation import normalize_text, validate_draft
from app.services.quiz_service import QuizBookLockedError, QuizBookNotFoundError
from app.services.rag.context import build_contexts

logger = logging.getLogger(__name__)


class QuizGenerationJobNotFoundError(Exception):
    def __init__(self, job_id: int) -> None:
        self.job_id = job_id
        super().__init__(f"Quiz generation job {job_id} not found")


class DocumentNotInProjectError(Exception):
    def __init__(self, document_id: int) -> None:
        self.document_id = document_id
        super().__init__(f"Document {document_id} is not in this project")


def _load_documents(
    documents: DocumentRepository,
    versions: DocumentVersionRepository,
    project_id: int,
    document_ids: list[int],
) -> list[tuple[Document, list[DocumentChunk]]]:
    """대상 문서와 그 현재 버전의 청크를 등장 순서대로 모은다"""
    out: list[tuple[Document, list[DocumentChunk]]] = []
    for document_id in document_ids:
        doc = documents.get(document_id)
        if doc is None or doc.project_id != project_id:
            raise DocumentNotInProjectError(document_id)
        if doc.current_version_id is None:
            out.append((doc, []))
            continue
        out.append((doc, versions.list_chunks(doc.current_version_id)))
    return out


class QuizGenerationService:
    def __init__(
        self,
        jobs: QuizGenerationJobRepository,
        documents: DocumentRepository,
        versions: DocumentVersionRepository,
        books: QuizBookRepository,
        sessions: QuizSessionRepository,
        settings: Settings,
        activity: ActivityService,
    ) -> None:
        self.jobs = jobs
        self.documents = documents
        self.versions = versions
        self.books = books
        self.sessions = sessions
        self.settings = settings
        self.activity = activity

    def start(
        self, project_id: int, user_id: int, payload: QuizGenerateRequest
    ) -> QuizGenerationJob:
        """검증 후 RUNNING 잡을 만들어 반환/ 실제 생성은 백그라운드에서 진행"""
        count = min(payload.count, self.settings.quiz_gen_max_questions)

        loaded = _load_documents(
            self.documents, self.versions, project_id, payload.document_ids
        )
        if not any(chunks for _, chunks in loaded):
            raise NoChunksError("대상 문서에 청크가 없습니다 (아직 파싱/청킹 전입니다)")

        if payload.quiz_book_id is not None:
            book = self.books.get(payload.quiz_book_id)
            if book is None or book.project_id != project_id:
                raise QuizBookNotFoundError(payload.quiz_book_id)
            # 기존 잠금 정책 재사용 — 응시 이력이 있는 문제집에는 문항을 추가할 수 없다
            if self.sessions.has_sessions(book.id):
                raise QuizBookLockedError(book.id)

        job = self.jobs.add(
            QuizGenerationJob(
                project_id=project_id,
                user_id=user_id,
                quiz_book_id=payload.quiz_book_id,
                status=QUIZ_GEN_STATUS_RUNNING,
                params={
                    "document_ids": payload.document_ids,
                    "count": count,
                    "types": [t.value for t in payload.types],
                    "difficulty": payload.difficulty.value if payload.difficulty else None,
                    "exclude_duplicates": payload.exclude_duplicates,
                },
                requested_count=count,
                created_count=0,
                question_ids=[],
            )
        )
        self.activity.record(
            Action.QUIZ_GENERATE_START,
            project_id=project_id,
            target_type="quiz_generation_job",
            target_id=job.id,
            meta={"count": count, "document_ids": payload.document_ids},
        )
        return job

    def get_job(self, job_id: int, user_id: int) -> QuizGenerationJob:
        job = self.jobs.get(job_id)
        if job is None or job.user_id != user_id:
            raise QuizGenerationJobNotFoundError(job_id)
        return job


_NOTIFY_MESSAGES = {
    Action.QUIZ_GENERATE_COMPLETE: (
        NotificationType.QUIZ_GENERATE_COMPLETE,
        lambda created: (
            "AI 문제 생성 완료",
            f"{created}개의 문제가 문제은행에 추가됐습니다." if created else "생성된 문제가 없습니다.",
        ),
    ),
    Action.QUIZ_GENERATE_FAIL: (
        NotificationType.QUIZ_GENERATE_FAIL,
        lambda _created: ("AI 문제 생성 실패", "문제 생성 중 오류가 발생했습니다."),
    ),
}


def run_quiz_generation_task(job_id: int) -> None:
    """BackgroundTasks 진입점 — 자체 세션으로 배치 생성을 수행하고 잡을 갱신한다."""
    db = SessionLocal()
    try:
        settings = get_settings()
        jobs = QuizGenerationJobRepository(db)
        questions = QuizQuestionRepository(db)
        books = QuizBookRepository(db)

        job = jobs.get(job_id)
        if job is None:
            logger.warning("run_quiz_generation_task: job %s not found", job_id)
            return

        params = job.params or {}
        actor = UserRepository(db).get(job.user_id)
        activity = activity_service_for(db, actor=actor)
        notifications = notification_service_for(db, settings)

        def finish(action: str, created: int) -> None:
            activity.record(
                action,
                project_id=job.project_id,
                target_type="quiz_generation_job",
                target_id=job.id,
                meta={"created": created, "requested": job.requested_count},
            )
            if actor is None or action not in _NOTIFY_MESSAGES:
                return
            notification_type, message = _NOTIFY_MESSAGES[action]
            title, body = message(created)
            notifications.notify(
                actor.id,
                type=notification_type,
                title=title,
                body=body,
                url="/quiz/bank",
                meta={
                    "job_id": job.id,
                    "project_id": job.project_id,
                    "created_count": created,
                },
            )

        try:
            provider = get_llm_provider(settings)
            job.provider = provider.name

            loaded = _load_documents(
                DocumentRepository(db),
                DocumentVersionRepository(db),
                job.project_id,
                list(params.get("document_ids") or []),
            )
            batches = plan_batches(
                loaded,
                count=job.requested_count,
                questions_per_call=settings.quiz_gen_questions_per_call,
                batch_max_chars=settings.quiz_gen_batch_max_chars,
            )

            allowed_types = set(params.get("types") or [])
            difficulty = params.get("difficulty")
            avoid_texts: list[str] = []
            if params.get("exclude_duplicates"):
                avoid_texts = questions.list_recent_texts(
                    job.project_id,
                    document_ids=list(params.get("document_ids") or []),
                    limit=settings.quiz_gen_avoid_sample,
                )
            seen = {normalize_text(t) for t in avoid_texts}

            def _run(batch: GenerationBatch):
                contexts = build_contexts(batch.chunks, settings.rag_context_max_chars)
                drafts = provider.generate_quiz(
                    contexts,
                    count=batch.question_count,
                    types=sorted(allowed_types),
                    difficulty=difficulty,
                    avoid_texts=avoid_texts,
                )
                return batch, contexts, drafts

            created_ids: list[int] = list(job.question_ids or [])
            failures: list[str] = []
            succeeded = 0
            dropped_invalid = 0
            dropped_duplicate = 0

            with ThreadPoolExecutor(
                max_workers=min(settings.quiz_gen_concurrency, len(batches) or 1)
            ) as pool:
                futures = [pool.submit(_run, b) for b in batches]
                for future in futures:
                    try:
                        batch, contexts, drafts = future.result()
                    except LLMError as exc:
                        failures.append(str(exc))
                        continue
                    succeeded += 1

                    by_index = {
                        c.index: batch.chunks[i] for i, c in enumerate(contexts)
                    }
                    added = 0
                    for draft in drafts:
                        clean, reason = validate_draft(
                            draft,
                            allowed_types=allowed_types,
                            requested_difficulty=difficulty,
                        )
                        if clean is None:
                            dropped_invalid += 1
                            logger.info("퀴즈 초안 제외: %s", reason)
                            continue
                        key = normalize_text(clean.text)
                        if key in seen:
                            dropped_duplicate += 1
                            logger.info("퀴즈 초안 제외: 중복 문항")
                            continue
                        seen.add(key)

                        hit = by_index.get(draft.source_index or -1)
                        question = questions.add(
                            QuizQuestion(
                                project_id=job.project_id,
                                source_document_id=batch.document.id,
                                type=clean.type,
                                text=clean.text,
                                options=clean.options,
                                correct_answer=clean.correct_answer,
                                explanation=clean.explanation,
                                difficulty=clean.difficulty,
                                tags=clean.tags,
                                source_location=(hit.label() if hit else None),
                                generation_type=GENERATION_TYPE_AI,
                                review_status=REVIEW_STATUS_DRAFT,
                            )
                        )
                        db.flush()
                        created_ids.append(question.id)
                        added += 1

                    if added:
                        job.created_count = len(created_ids)
                        job.question_ids = list(created_ids)
                        db.commit()

            if job.quiz_book_id is not None and created_ids:
                books.add_questions(job.quiz_book_id, created_ids)

            if succeeded == 0 and batches:
                job.status = QUIZ_GEN_STATUS_FAILED
                job.error = "; ".join(failures)[:2000] or "모든 배치 생성에 실패했습니다"
                db.commit()
                logger.warning("quiz generation %s failed: %s", job_id, job.error)
                finish(Action.QUIZ_GENERATE_FAIL, 0)
                return

            job.status = QUIZ_GEN_STATUS_COMPLETED
            job.created_count = len(created_ids)
            job.question_ids = list(created_ids)

            notes: list[str] = []
            if failures:
                notes.append(f"일부 배치 실패({len(failures)}건): " + "; ".join(failures)[:1200])
            if len(created_ids) < job.requested_count:
                reasons = []
                if dropped_duplicate:
                    reasons.append(f"중복 {dropped_duplicate}건")
                if dropped_invalid:
                    reasons.append(f"형식 오류 {dropped_invalid}건")
                if reasons:
                    notes.append("제외된 초안: " + ", ".join(reasons))
                elif not failures:
                    notes.append("모델이 요청한 수보다 적은 문항을 생성했습니다")
            if notes:
                job.error = " / ".join(notes)[:2000]
            db.commit()
            logger.info(
                "quiz generation %s done: %s/%s questions over %s batches",
                job_id, len(created_ids), job.requested_count, len(batches),
            )
            finish(Action.QUIZ_GENERATE_COMPLETE, len(created_ids))

        except (NoChunksError, DocumentNotInProjectError) as exc:
            db.rollback()
            job = jobs.get(job_id)
            if job is not None:
                job.status = QUIZ_GEN_STATUS_FAILED
                job.error = str(exc)
                db.commit()
            logger.warning("quiz generation %s failed: %s", job_id, exc)
            finish(Action.QUIZ_GENERATE_FAIL, 0)
        except LLMError as exc:
            db.rollback()
            job = jobs.get(job_id)
            if job is not None:
                job.status = QUIZ_GEN_STATUS_FAILED
                job.error = str(exc)
                db.commit()
            logger.warning("quiz generation %s failed: %s", job_id, exc)
            finish(Action.QUIZ_GENERATE_FAIL, 0)
    finally:
        db.close()


def get_quiz_generation_service(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    activity: ActivityService = Depends(get_activity_service),
) -> QuizGenerationService:
    return QuizGenerationService(
        QuizGenerationJobRepository(db),
        DocumentRepository(db),
        DocumentVersionRepository(db),
        QuizBookRepository(db),
        QuizSessionRepository(db),
        settings,
        activity,
    )
