from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai_analysis_result import AiAnalysisResult


class AiAnalysisResultRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, result: AiAnalysisResult) -> AiAnalysisResult:
        self.db.add(result)
        self.db.commit()
        self.db.refresh(result)
        return result

    def get(self, analysis_id: int) -> AiAnalysisResult | None:
        return self.db.get(AiAnalysisResult, analysis_id)

    def list_by_document(
        self, document_id: int, *, analysis_type: str | None = None
    ) -> list[AiAnalysisResult]:
        stmt = select(AiAnalysisResult).where(
            AiAnalysisResult.document_id == document_id
        )
        if analysis_type is not None:
            stmt = stmt.where(AiAnalysisResult.analysis_type == analysis_type)
        return list(self.db.scalars(stmt.order_by(AiAnalysisResult.id.desc())))
