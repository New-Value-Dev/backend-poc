from pydantic import BaseModel, Field


class UrlImportRequest(BaseModel):
    url: str = Field(
        description="기사 본문을 가져올 mediahub.seoul.go.kr 기사 URL",
        examples=["https://mediahub.seoul.go.kr/archives/2019284"],
    )


class UrlImportResult(BaseModel):
    markdown: str = Field(description="추출한 기사 본문을 변환한 마크다운")
