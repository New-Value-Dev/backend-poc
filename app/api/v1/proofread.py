from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Path,
    Query,
    status,
)

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.proofread import AnalysisSummary, ProofreadResult
from app.services.document_service import DocumentNotFoundError, VersionNotFoundError
from app.services.proofread_service import (
    AnalysisNotFoundError,
    DocumentNotReadyError,
    ProofreadService,
    build_result,
    get_proofread_service,
    run_proofread_task,
)

router = APIRouter(tags=["ai-proofread"])

DocumentIdPath = Annotated[int, Path(description="문서 id", examples=[1])]
AnalysisIdPath = Annotated[
    int,
    Path(description="분석 id — 교정 시작 응답의 `id`", examples=[1]),
]

AUTH_RESPONSES = {401: {"description": "토큰 없음/만료/무효"}}


@router.post(
    "/documents/{document_id}/proofread",
    response_model=ProofreadResult,
    status_code=status.HTTP_202_ACCEPTED,
    summary="오탈자 검증 시작 (비동기)",
    response_description="`status=\"RUNNING\"`, `findings=[]` 인 분석 레코드(202)",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "문서가 없거나 저장된 버전이 없음"},
        409: {"description": "아직 파싱이 끝나지 않아 검사할 섹션이 없음"},
    },
)
def proofread_document(
    document_id: DocumentIdPath,
    background_tasks: BackgroundTasks,
    service: ProofreadService = Depends(get_proofread_service),
    current_user: User = Depends(get_current_user),
) -> ProofreadResult:
    """교정을 시작하고 즉시 202와 RUNNING 레코드를 반환한다. 실제 GPT 호출은 백그라운드에서 진행되며 결과는 분석 상세 조회를 폴링해 확인한다"""
    try:
        record = service.create_pending(document_id, created_by=str(current_user.id))
    except DocumentNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Document {document_id} not found"
        ) from None
    except VersionNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No stored version for this document"
        ) from None
    except DocumentNotReadyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None

    background_tasks.add_task(run_proofread_task, record.id)
    return build_result(record, [], 0)


@router.get(
    "/documents/{document_id}/analyses",
    response_model=list[AnalysisSummary],
    summary="AI 분석 이력",
    response_description="최신순 메타 목록(결과 본문은 빠져 있다)",
    responses={**AUTH_RESPONSES, 404: {"description": "문서 없음"}},
)
def list_analyses(
    document_id: DocumentIdPath,
    type: Annotated[
        str | None,
        Query(
            description=(
                "분석 종류로 거른다. 지금 실제로 쌓이는 값은 `proofread` 뿐이고 "
                "`classify`/`validate`/`related` 는 예약된 값이다."
            ),
            examples=["proofread"],
        ),
    ] = None,
    service: ProofreadService = Depends(get_proofread_service),
    _: User = Depends(get_current_user),
) -> list[AnalysisSummary]:
    """이 문서에 대해 실행된 AI 분석 목록을 최신순으로 돌려준다. 결과 본문 없이 메타 정보만 담긴다"""
    try:
        return service.list_analyses(document_id, analysis_type=type)
    except DocumentNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Document {document_id} not found"
        ) from None


@router.get(
    "/documents/{document_id}/analyses/{analysis_id}",
    response_model=ProofreadResult,
    summary="분석 결과 상세 (폴링용)",
    response_description="`status` + 완료 시 `findings`",
    responses={**AUTH_RESPONSES, 404: {"description": "해당 분석 없음"}},
)
def get_analysis(
    document_id: DocumentIdPath,
    analysis_id: AnalysisIdPath,
    service: ProofreadService = Depends(get_proofread_service),
    _: User = Depends(get_current_user),
) -> ProofreadResult:
    """분석 결과를 조회한다. 교정 시작 후 이걸 폴링해 완료를 감지한다"""
    try:
        return service.get_analysis(document_id, analysis_id)
    except AnalysisNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Analysis {analysis_id} not found"
        ) from None
