from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.rag_query import RagQuery


class RagQueryRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, query: RagQuery) -> RagQuery:
        self.db.add(query)
        self.db.commit()
        self.db.refresh(query)
        return query

    def list_recent(self, *, limit: int) -> list[RagQuery]:
        stmt = select(RagQuery).order_by(RagQuery.id.desc()).limit(limit)
        return list(self.db.scalars(stmt))
