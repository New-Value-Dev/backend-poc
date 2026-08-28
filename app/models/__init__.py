"""SQLAlchemy 모델 모음.

Alembic autogenerate 가 모든 테이블을 인식하도록 여기서 전부 import 한다.
새 모델을 추가하면 반드시 이 목록에도 등록한다.
"""

from app.models.activity_log import ActivityLog
from app.models.ai_analysis_result import AiAnalysisResult
from app.models.benchmark import (
    BenchmarkDataset,
    BenchmarkQuestion,
    BenchmarkResult,
    BenchmarkRun,
)
from app.models.chunk_embedding import ChunkEmbedding
from app.models.chunking_config import ChunkingConfig
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_section import DocumentSection
from app.models.document_version import DocumentVersion
from app.models.embedding_job import EmbeddingJob
from app.models.embedding_model import EmbeddingModel
from app.models.exchange_rate_cache import ExchangeRateCache
from app.models.folder import Folder
from app.models.llm_usage_log import LLMUsageLog
from app.models.model_price_cache import ModelPriceCache
from app.models.notification import Notification
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.push_subscription import PushSubscription
from app.models.quiz_answer import QuizAnswer
from app.models.quiz_book import QuizBook
from app.models.quiz_book_assignee import QuizBookAssignee
from app.models.quiz_book_question import QuizBookQuestion
from app.models.quiz_generation_job import QuizGenerationJob
from app.models.quiz_question import QuizQuestion
from app.models.quiz_session import QuizSession
from app.models.rag_conversation import RagConversation
from app.models.rag_message import RagMessage
from app.models.text_proofread_job import TextProofreadJob
from app.models.user import User

__all__ = [
    "User",
    "Project",
    "ProjectMember",
    "Folder",
    "Document",
    "DocumentVersion",
    "DocumentSection",
    "DocumentChunk",
    "EmbeddingModel",
    "ChunkEmbedding",
    "ChunkingConfig",
    "EmbeddingJob",
    "BenchmarkDataset",
    "BenchmarkQuestion",
    "BenchmarkRun",
    "BenchmarkResult",
    "AiAnalysisResult",
    "ActivityLog",
    "PushSubscription",
    "Notification",
    "TextProofreadJob",
    "QuizQuestion",
    "QuizBook",
    "QuizBookAssignee",
    "QuizBookQuestion",
    "QuizSession",
    "QuizAnswer",
    "QuizGenerationJob",
    "RagConversation",
    "RagMessage",
    "LLMUsageLog",
    "ExchangeRateCache",
    "ModelPriceCache",
]
