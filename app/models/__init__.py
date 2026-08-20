"""SQLAlchemy 모델 모음.

Alembic autogenerate 가 모든 테이블을 인식하도록 여기서 전부 import 한다.
새 모델을 추가하면 반드시 이 목록에도 등록한다.
"""

from app.models.activity_log import ActivityLog
from app.models.ai_analysis_result import AiAnalysisResult
from app.models.chunk_embedding import ChunkEmbedding
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_section import DocumentSection
from app.models.document_version import DocumentVersion
from app.models.embedding_model import EmbeddingModel
from app.models.folder import Folder
from app.models.project import Project
from app.models.rag_query import RagQuery
from app.models.user import User

__all__ = [
    "User",
    "Project",
    "Folder",
    "Document",
    "DocumentVersion",
    "DocumentSection",
    "DocumentChunk",
    "EmbeddingModel",
    "ChunkEmbedding",
    "AiAnalysisResult",
    "ActivityLog",
    "RagQuery",
]
