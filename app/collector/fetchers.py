"""수집함 공통: 가져온 항목 형식과 텍스트 정리."""
import html
import re
from dataclasses import dataclass, field
from datetime import datetime

TIMEOUT = 15
COMMENT_LIMIT = 2000  # 댓글 1개 최대 글자 수


@dataclass
class Item:
    site: str  # reddit / youtube / x
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


def clean_text(raw, limit=None, keep_lines=False):
    """HTML 태그 제거·공백 정리. keep_lines=True 면 줄바꿈(문단)은 유지한다."""
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    if keep_lines:
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
    else:
        text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text
