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
from app.schemas.proofread import (
    AnalysisSummary,
    ApplyCorrectionsResponse,
    FindingStatusUpdate,
    ProofreadResult,
)
from app.services.activity_service import Action, ActivityService, get_activity_service
from app.services.correction_service import (
    AlreadyAppliedError,
    CorrectionService,
    NoAcceptedFindingsError,
    UnsupportedFileTypeError,
    get_correction_service,
)
from app.services.document_service import (
    DocumentNotFoundError,
    DocumentService,
    VersionNotFoundError,
    get_document_service,
)
from app.services.parsing_service import run_parse_task
from app.services.proofread_service import (
    AnalysisNotCompletedError,
    AnalysisNotFoundError,
    DocumentNotReadyError,
    FindingNotFoundError,
    ProofreadService,
    build_result,
    get_proofread_service,
    run_proofread_task,
)
from app.services.project_service import (
    ProjectForbiddenError,
    ProjectNotFoundError,
    ProjectService,
    get_project_service,
)

router = APIRouter(tags=["ai-proofread"])

DocumentIdPath = Annotated[int, Path(description="문서 id", examples=[1])]
AnalysisIdPath = Annotated[
    int,
    Path(description="분석 id — 교정 시작 응답의 `id`", examples=[1]),
]

AUTH_RESPONSES = {401: {"description": "토큰 없음/만료/무효"}}
FORBIDDEN_RESPONSE = {403: {"description": "이 문서가 속한 프로젝트에 접근할 권한이 없음"}}


def check_document_access(
    document_id: DocumentIdPath,
    service: DocumentService = Depends(get_document_service),
    projects: ProjectService = Depends(get_project_service),
    current_user: User = Depends(get_current_user),
) -> None:
    """documents.py 의 동명 dependency와 같은 역할"""
    try:
        doc = service.get_document(document_id)
    except DocumentNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Document {document_id} not found"
        ) from None
    try:
        projects.check_access(doc.project_id, current_user)
    except ProjectForbiddenError:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "이 문서에 접근할 권한이 없습니다"
        ) from None
    except ProjectNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Document {document_id} not found"
        ) from None


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
        **FORBIDDEN_RESPONSE,
    },
)
def proofread_document(
    document_id: DocumentIdPath,
    background_tasks: BackgroundTasks,
    service: ProofreadService = Depends(get_proofread_service),
    current_user: User = Depends(get_current_user),
    _: None = Depends(check_document_access),
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
    responses={**AUTH_RESPONSES, 404: {"description": "문서 없음"}, **FORBIDDEN_RESPONSE},
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
    _: None = Depends(check_document_access),
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
    responses={**AUTH_RESPONSES, 404: {"description": "해당 분석 없음"}, **FORBIDDEN_RESPONSE},
)
def get_analysis(
    document_id: DocumentIdPath,
    analysis_id: AnalysisIdPath,
    service: ProofreadService = Depends(get_proofread_service),
    _: None = Depends(check_document_access),
) -> ProofreadResult:
    """분석 결과를 조회한다. 교정 시작 후 이걸 폴링해 완료를 감지한다"""
    try:
        return service.get_analysis(document_id, analysis_id)
    except AnalysisNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Analysis {analysis_id} not found"
        ) from None


FindingIdPath = Annotated[
    str, Path(description="finding id — 분석 결과의 finding.id", examples=["f0"])
]


@router.patch(
    "/documents/{document_id}/analyses/{analysis_id}/findings/{finding_id}",
    response_model=ProofreadResult,
    summary="finding 승인/반려 상태 변경",
    response_description="갱신된 findings 목록을 포함한 전체 분석 결과",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "분석 또는 finding 없음"},
        409: {"description": "분석이 아직 완료되지 않음"},
        **FORBIDDEN_RESPONSE,
    },
)
def update_finding_status(
    document_id: DocumentIdPath,
    analysis_id: AnalysisIdPath,
    finding_id: FindingIdPath,
    body: FindingStatusUpdate,
    service: ProofreadService = Depends(get_proofread_service),
    _: None = Depends(check_document_access),
) -> ProofreadResult:
    """finding 하나를 accepted/rejected/pending 으로 표시한다. apply 는 accepted 상태만 반영한다"""
    try:
        return service.set_finding_status(document_id, analysis_id, finding_id, body.status)
    except AnalysisNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Analysis {analysis_id} not found"
        ) from None
    except FindingNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Finding {finding_id} not found"
        ) from None
    except AnalysisNotCompletedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None


@router.post(
    "/documents/{document_id}/analyses/{analysis_id}/apply",
    response_model=ApplyCorrectionsResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="승인된 교정을 원본 파일에 반영 (새 버전 생성)",
    response_description="새 버전 id + 반영/스킵 개수(202, 파싱은 백그라운드에서 이어짐)",
    responses={
        **AUTH_RESPONSES,
        400: {"description": "지원하지 않는 파일 형식이거나 승인된 finding이 없음/전부 매칭 실패"},
        404: {"description": "분석 없음"},
        409: {"description": "분석이 미완료 상태이거나 이미 적용됨"},
        **FORBIDDEN_RESPONSE,
    },
)
def apply_corrections(
    document_id: DocumentIdPath,
    analysis_id: AnalysisIdPath,
    background_tasks: BackgroundTasks,
    corrections: CorrectionService = Depends(get_correction_service),
    activity: ActivityService = Depends(get_activity_service),
    _: None = Depends(check_document_access),
) -> ApplyCorrectionsResponse:
    """accepted 상태인 finding들을 DOCX/HWPX는 실제 편집, PDF는 시각적 패치로 반영해
    새 문서 버전을 만들고, 반영된 파일을 다시 파싱/청킹하도록 백그라운드 작업을 건다"""
    try:
        outcome = corrections.apply(document_id, analysis_id)
    except AnalysisNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Analysis {analysis_id} not found"
        ) from None
    except AnalysisNotCompletedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except AlreadyAppliedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except NoAcceptedFindingsError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    except VersionNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No stored version for this analysis"
        ) from None

    background_tasks.add_task(run_parse_task, outcome.new_version.id)

    doc = corrections.documents.get_document(document_id)
    activity.record(
        Action.CORRECTIONS_APPLY,
        project_id=doc.project_id,
        target_type="document",
        target_id=document_id,
        target_label=doc.name,
        meta={
            "analysis_id": analysis_id,
            "new_version_id": outcome.new_version.id,
            "applied_count": outcome.applied_count,
            "skipped_count": outcome.skipped_count,
        },
    )
    return ApplyCorrectionsResponse(
        analysis_id=analysis_id,
        document_id=document_id,
        new_version_id=outcome.new_version.id,
        new_version_no=outcome.new_version.version_no,
        applied_count=outcome.applied_count,
        skipped_count=outcome.skipped_count,
        skipped_reasons=outcome.skipped_reasons,
    )
