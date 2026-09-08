from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

ALLOWED_HOST = "mediahub.seoul.go.kr"
ALLOWED_URL_PREFIX = f"https://{ALLOWED_HOST}"
REQUEST_TIMEOUT = 10.0

_BLOCK_JOIN = "\n\n"
_SKIP_TAGS = {"script", "style", "img", "video", "source", "button", "iframe", "audio"}
_BOLD_TAGS = {"b", "strong"}
_ITALIC_TAGS = {"i", "em"}
_HEADING_PREFIXES = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####"}


class InvalidArticleUrlError(Exception):
    """허용된 도메인(mediahub.seoul.go.kr)이 아니거나 URL 형식이 잘못됨"""


class ArticleFetchError(Exception):
    """원본 페이지를 가져오는 데 실패함"""


class ArticleNotFoundError(Exception):
    """본문 영역(.news_detail_cont .article .story_area)을 찾지 못함"""


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        raise InvalidArticleUrlError(
            f"{ALLOWED_URL_PREFIX} 로 시작하는 URL만 입력할 수 있습니다."
        )


def _inline_text(node: Tag) -> str:
    """인라인 요소를 재귀적으로 순회하며 HTML 태그를 실제 텍스트로 변환한다 (br → 개행, b/strong → **강조** 등)."""
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
            continue
        if not isinstance(child, Tag):
            continue
        name = child.name.lower()
        if name in _SKIP_TAGS:
            continue
        if name == "br":
            parts.append("\n")
            continue
        raw = _inline_text(child)
        inner = raw.strip()
        if not inner:
            continue
        # 여는/닫는 마커 바로 옆에 공백이 있으면 CommonMark가 강조로 파싱하지 않으므로 안쪽은
        # 지우되, 원본에 있던 공백은 단어 경계가 사라지지 않도록 마커 바깥에 그대로 남겨둔다.
        leading = " " if raw[:1].isspace() else ""
        trailing = " " if raw[-1:].isspace() else ""
        if name in _BOLD_TAGS:
            parts.append(f"{leading}**{inner}**{trailing}")
        elif name in _ITALIC_TAGS:
            parts.append(f"{leading}*{inner}*{trailing}")
        else:
            parts.append(f"{leading}{inner}{trailing}")
    return "".join(parts)


def _collapse_newline_run(match: re.Match[str]) -> str:
    # 원본 소스의 들여쓰기(공백/탭)가 줄바꿈 사이에 섞여 있으면 "\n{3,}" 하나로는 못 걸러지므로,
    # 줄바꿈이 섞인 공백 구간을 줄바꿈 개수 기준으로 다시 정규화한다(2개 이상 → 빈 줄 하나, 1개 → 단순 개행).
    return "\n\n" if match.group(0).count("\n") >= 2 else "\n"


def _normalize(text: str) -> str:
    text = text.replace("\xa0", " ")
    # 원본이 CRLF(\r\n)나 단독 \r을 쓰는 경우가 있어 전부 \n으로 통일한 뒤 줄바꿈을 정리한다.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]*\n[ \t\n]*", _collapse_newline_run, text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _extract_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("div.news_detail_cont")
    if container is None:
        raise ArticleNotFoundError("기사 본문 영역을 찾을 수 없습니다. URL을 확인해 주세요.")

    story_areas = container.select("div.article div.story_area")
    if not story_areas:
        raise ArticleNotFoundError("기사 본문 영역을 찾을 수 없습니다. URL을 확인해 주세요.")

    blocks: list[str] = []
    for area in story_areas:
        for child in area.children:
            if not isinstance(child, Tag):
                continue
            name = child.name.lower()
            if name in _SKIP_TAGS:
                continue
            text = _inline_text(child).strip()
            if not text:
                continue
            prefix = _HEADING_PREFIXES.get(name)
            blocks.append(f"{prefix} {text}" if prefix else text)

    if not blocks:
        raise ArticleNotFoundError("기사 본문 내용을 찾을 수 없습니다.")

    return _normalize(_BLOCK_JOIN.join(blocks))


class UrlImportService:
    """mediahub.seoul.go.kr 기사 URL을 서버에서 대신 가져와(CORS 우회) 기사 본문만 마크다운으로 변환한다."""

    def fetch_article_markdown(self, url: str) -> str:
        _validate_url(url)
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
                response = client.get(url)
        except httpx.HTTPError as exc:
            raise ArticleFetchError(f"페이지를 가져오지 못했습니다: {exc}") from exc

        # 리다이렉트로 다른 도메인으로 빠졌는지 최종 URL도 다시 확인 (SSRF 방지)
        if urlparse(str(response.url)).hostname != ALLOWED_HOST:
            raise InvalidArticleUrlError(
                f"{ALLOWED_URL_PREFIX} 로 시작하는 URL만 입력할 수 있습니다."
            )
        if response.status_code != 200:
            raise ArticleFetchError(
                f"페이지를 가져오지 못했습니다 (HTTP {response.status_code})."
            )

        return _extract_markdown(response.text)


def get_url_import_service() -> UrlImportService:
    return UrlImportService()
