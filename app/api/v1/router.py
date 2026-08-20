from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.documents import router as documents_router
from app.api.v1.folders import router as folders_router
from app.api.v1.health import router as health_router
from app.api.v1.mypage import router as mypage_router
from app.api.v1.proofread import router as proofread_router
from app.api.v1.projects import router as projects_router
from app.api.v1.rag import router as rag_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(dashboard_router)
api_router.include_router(mypage_router)
api_router.include_router(projects_router)
api_router.include_router(folders_router)
api_router.include_router(documents_router)
api_router.include_router(proofread_router)
api_router.include_router(rag_router)
