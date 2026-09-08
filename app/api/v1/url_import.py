from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.url_import import UrlImportRequest, UrlImportResult
from app.services.url_import_service import (
    ArticleFetchError,
    ArticleNotFoundError,
    InvalidArticleUrlError,
    UrlImportService,
    get_url_import_service,
)

router = APIRouter(tags=["text-import"])


@router.post(
    "/text/import-url",
    response_model=UrlImportResult,
    summary="mediahub.seoul.go.kr 기사 URL에서 본문을 가져와 마크다운으로 변환",
    response_description="변환된 본문 마크다운",
    responses={
        401: {"description": "토큰 없음/만료/무효"},
        400: {"description": "허용된 도메인(mediahub.seoul.go.kr)이 아닌 URL"},
        404: {"description": "본문 영역을 찾을 수 없음"},
        502: {"description": "원본 페이지를 가져오지 못함"},
    },
)
def import_url(
    body: UrlImportRequest,
    service: UrlImportService = Depends(get_url_import_service),
    _: User = Depends(get_current_user),
) -> UrlImportResult:
    """mediahub.seoul.go.kr 기사 페이지를 서버에서 대신 가져와(CORS 우회) 본문 영역만 추출하고,
    HTML 태그를 에디터가 이해하는 마크다운으로 변환한다 (h2 → 제목, br → 개행 등)."""
    try:
        markdown = service.fetch_article_markdown(body.url)
    except InvalidArticleUrlError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    except ArticleNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except ArticleFetchError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None
    return UrlImportResult(markdown=markdown)
