"""운영자 브라우저에서 가져온 게시물(Reddit·YouTube·X)을 수집함 항목으로 바꾼다.

각 사이트는 서버의 자동 수집을 막거나 유료 API 를 요구하므로, 운영자가 게시물 페이지에서
'BestKorea로 가져오기' 버튼(북마클릿)을 누르면 브라우저가 페이지의 데이터를 읽어 넘겨준다.
서버는 그 사이트에 접속하지 않고, 받은 데이터를 검증·정리만 한다 (페이지가 보낸 값은 신뢰하지 않음).

  Reddit  : 게시글 주소 + '.json' 응답 원본
  YouTube : {"id","title","text","author","published","num_comments","comments":[...]}
  X       : {"id","handle","name","text","lang","image","published","num_comments","comments":[...]}
"""
import html
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from ..constants import region_for_lang
from .classify import classify
from .fetchers import COMMENT_LIMIT, Item, clean_text

MAX_PAYLOAD = 5 * 1024 * 1024
MAX_COMMENTS_IN = 500
SITES = ("reddit", "youtube", "x")
REDDIT_PERMALINK_RE = re.compile(r"^/r/[A-Za-z0-9_]+/comments/[a-z0-9]+(/[^\s?#]*)?$")
YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
X_ID_RE = re.compile(r"^\d{1,25}$")
X_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
IMAGE_HOSTS = {"youtube": ("i.ytimg.com",), "x": ("pbs.twimg.com",)}


class ImportError_(Exception):
    """사용자에게 그대로 보여줄 가져오기 오류."""


# ------------------------------------------------------------------ 공통
def _parse_time(value):
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None)
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
    except (ValueError, OverflowError, OSError):
        return None


def _int(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _strip_mentions(text):
    """X 답글 앞에 붙는 @아이디 목록 제거."""
    return re.sub(r"^(?:@\w+\s+)+", "", text or "").strip()


def _clean_comments(raw, max_comments, strip_mentions=False):
    if not isinstance(raw, list):
        return []
    out = []
    for c in raw[:MAX_COMMENTS_IN]:
        if not isinstance(c, dict):
            continue
        body = str(c.get("body") or "")
        body = clean_text(_strip_mentions(body) if strip_mentions else body, COMMENT_LIMIT, keep_lines=True)
        if not body:
            continue
        out.append(dict(author=clean_text(str(c.get("author") or "unknown"), 100), body=body, score=_int(c.get("score"))))
    out.sort(key=lambda c: c["score"], reverse=True)
    return out[:max_comments]


def _check_comments(num_comments, comments, min_comments):
    total = max(num_comments, len(comments))
    if total < min_comments:
        raise ImportError_(f"댓글이 {total}개라 수집 기준({min_comments}개 이상)에 못 미칩니다.")
    if not comments:
        raise ImportError_("댓글을 하나도 읽지 못했습니다. 페이지에서 댓글이 보이는지 확인한 뒤 다시 눌러 주세요.")
    return total


def _safe_image(url, site):
    if not isinstance(url, str):
        return None
    p = urlparse(url)
    return url if p.scheme == "https" and p.hostname in IMAGE_HOSTS.get(site, ()) and len(url) <= 2000 else None


def _load(text):
    if not text or len(text) > MAX_PAYLOAD:
        raise ImportError_("가져온 데이터가 비어 있거나 너무 큽니다.")
    try:
        return json.loads(text)
    except ValueError:
        raise ImportError_("가져온 데이터 형식이 올바르지 않습니다.")


def detect(text):
    """붙여넣은 내용에서 (사이트, 데이터 문자열)을 판별. 버튼이 복사해 둔 {"site","json"} 또는 Reddit .json 원본."""
    data = _load(text)
    if isinstance(data, dict) and data.get("site") in SITES and isinstance(data.get("json"), str):
        return data["site"], data["json"]
    if isinstance(data, list):
        return "reddit", text
    raise ImportError_("BestKorea로 가져오기 버튼이 복사한 내용이나 Reddit 게시글 .json 이 아닙니다.")


def parse(site, text, min_comments, max_comments):
    """(Item, 링크된 외부 기사 주소 또는 None)"""
    if site == "reddit":
        return parse_reddit(text, min_comments, max_comments)
    if site == "youtube":
        return parse_youtube(_load(text), min_comments, max_comments), None
    if site == "x":
        return parse_x(_load(text), min_comments, max_comments), None
    raise ImportError_("지원하지 않는 사이트입니다.")


# ------------------------------------------------------------------ Reddit
def _reddit_image(post):
    url = post.get("url_overridden_by_dest") or post.get("url") or ""
    if re.search(r"\.(jpe?g|png|gif|webp)$", url, re.I):
        return url
    try:
        return html.unescape(post["preview"]["images"][0]["source"]["url"])
    except (KeyError, IndexError, TypeError):
        return None


def parse_reddit(text, min_comments, max_comments):
    data = _load(text)
    try:
        post = data[0]["data"]["children"][0]["data"]
        children = data[1]["data"]["children"]
    except (KeyError, IndexError, TypeError):
        raise ImportError_("Reddit 게시글 데이터 형식이 아닙니다. 게시글 페이지에서 가져왔는지 확인하세요.")

    permalink = post.get("permalink") or ""
    if not REDDIT_PERMALINK_RE.match(permalink):
        raise ImportError_("Reddit 게시글 주소를 확인할 수 없습니다.")
    if post.get("over_18"):
        raise ImportError_("성인(NSFW) 게시글은 가져올 수 없습니다.")

    raw = []
    for child in children:
        if child.get("kind") != "t1":
            continue
        c = child.get("data") or {}
        body = (c.get("body") or "").strip()
        author = c.get("author") or ""
        if not body or body in ("[deleted]", "[removed]") or c.get("stickied") or author.lower() == "automoderator":
            continue
        raw.append(dict(author=author, body=body, score=c.get("score", 0)))
    comments = _clean_comments(raw, max_comments)
    num_comments = _check_comments(_int(post.get("num_comments")), comments, min_comments)

    external = None
    if not post.get("is_self"):
        external = post.get("url_overridden_by_dest") or post.get("url")
        if external and ("reddit.com" in external or "redd.it" in external or external == _reddit_image(post)
                         or not external.startswith(("http://", "https://"))):
            external = None

    title = clean_text(post.get("title"), 300)
    selftext = clean_text(post.get("selftext"), 20000, keep_lines=True)
    return Item(
        site="reddit", external_id=str(post.get("id", ""))[:50], title=title,
        url="https://www.reddit.com" + permalink, country=None, lang="en", summary=selftext,
        source_name=f"r/{post.get('subreddit', '')}", category=classify(f"{title} {selftext[:500]}"),
        published_at=_parse_time(post.get("created_utc")), image_url=_reddit_image(post),
        num_comments=num_comments, reactions=comments,
    ), (external[:2000] if external else None)


# ------------------------------------------------------------------ YouTube
def parse_youtube(data, min_comments, max_comments):
    if not isinstance(data, dict):
        raise ImportError_("YouTube 데이터 형식이 올바르지 않습니다.")
    vid = str(data.get("id") or "")
    if not YOUTUBE_ID_RE.match(vid):
        raise ImportError_("YouTube 영상 ID를 확인할 수 없습니다. 영상 페이지(youtube.com/watch?v=...)에서 눌러 주세요.")
    title = clean_text(str(data.get("title") or ""), 300)
    if not title:
        raise ImportError_("영상 제목을 읽지 못했습니다. 페이지가 다 열린 뒤 다시 눌러 주세요.")
    comments = _clean_comments(data.get("comments"), max_comments)
    num_comments = _check_comments(_int(data.get("num_comments")), comments, min_comments)
    text = clean_text(str(data.get("text") or ""), 20000, keep_lines=True)
    return Item(
        site="youtube", external_id=vid, title=title, url=f"https://www.youtube.com/watch?v={vid}",
        country=None, lang="", summary=text, source_name=clean_text(str(data.get("author") or ""), 200),
        category=classify(f"{title} {text[:500]}"), published_at=_parse_time(data.get("published")),
        image_url=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", num_comments=num_comments, reactions=comments,
    )


# ------------------------------------------------------------------ X
def parse_x(data, min_comments, max_comments):
    if not isinstance(data, dict):
        raise ImportError_("X 데이터 형식이 올바르지 않습니다.")
    tid, handle = str(data.get("id") or ""), str(data.get("handle") or "").lstrip("@")
    if not X_ID_RE.match(tid) or not X_HANDLE_RE.match(handle):
        raise ImportError_("X 게시물 주소를 확인할 수 없습니다. 게시물 페이지(x.com/아이디/status/숫자)에서 눌러 주세요.")
    text = clean_text(str(data.get("text") or ""), 20000, keep_lines=True)
    if not text:
        raise ImportError_("게시물 본문을 읽지 못했습니다. 페이지가 다 열린 뒤 다시 눌러 주세요.")
    comments = _clean_comments(data.get("comments"), max_comments, strip_mentions=True)
    num_comments = _check_comments(_int(data.get("num_comments")), comments, min_comments)
    name = clean_text(str(data.get("name") or ""), 100)
    return Item(
        site="x", external_id=tid, title=clean_text(text, 200), url=f"https://x.com/{handle}/status/{tid}",
        country=region_for_lang(data.get("lang")), lang=clean_text(str(data.get("lang") or ""), 10), summary=text,
        source_name=f"@{handle}" + (f" ({name})" if name else ""), category=classify(text),
        published_at=_parse_time(data.get("published")), image_url=_safe_image(data.get("image"), "x"),
        num_comments=num_comments, reactions=comments,
    )


STOP_REASONS = {
    "limit": "충분히 읽음",
    "idle": "더 불러올 댓글이 없음",
    "section": "댓글 목록이 끝나고 다른 섹션이 시작됨",
    "timeout": "45초 시간 초과",
}


def read_note(site, text, item):
    """가져오기 결과 안내: 읽은 댓글 수 / 전체 댓글 수와 멈춘 이유 (YouTube·X)."""
    if site not in ("youtube", "x"):
        return ""
    try:
        debug = json.loads(text).get("debug") or {}
    except (ValueError, AttributeError):
        debug = {}
    reason = STOP_REASONS.get(debug.get("stop"), "")
    note = f"전체 {item.num_comments:,}개 중 {len(item.reactions)}개 저장"
    if reason:
        note += f", 읽기를 멈춘 이유: {reason}"
    if debug.get("clicked"):
        note += f", '답글 더 보기' {debug['clicked']}번 누름"
    return note
