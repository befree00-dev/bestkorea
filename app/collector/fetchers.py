"""수집기 공통: 수집 항목 형식과 텍스트 정리."""
import html
import re
from dataclasses import dataclass, field
from datetime import datetime

TIMEOUT = 15
COMMENT_LIMIT = 2000  # 댓글 1개 최대 글자 수


@dataclass
class Item:
    site: str  # youtube / yahoo_jp / baidu ...
    external_id: str  # 사이트 안에서의 글 ID (예: YouTube videoId)
    title: str
    url: str
    country: str
    lang: str
    summary: str = ""  # 영상 설명·본문 발췌
    source_name: str = ""  # 채널명·매체명
    category: str | None = None
    published_at: datetime | None = None
    image_url: str | None = None
    num_comments: int = 0
    reactions: list = field(default_factory=list)  # [{"author","body","score"}]


def clean_text(raw, limit=None):
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


_HANGUL = re.compile(r"[가-힣]")
_LETTER = re.compile(r"\w", re.UNICODE)


def mostly_korean(text, threshold=0.3):
    """한글 비율이 높은 글(국내 콘텐츠)인지. '해외 반응'만 모으기 위해 제외할 때 사용."""
    letters = _LETTER.findall(text or "")
    if not letters:
        return False
    return len(_HANGUL.findall(text)) / len(letters) >= threshold
