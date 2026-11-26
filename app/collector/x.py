"""X(트위터) API v2 수집기 (공식 API, X_BEARER_TOKEN 필요, 유료 요금제).

X API 는 읽어 온 게시물 수만큼 월 사용량(또는 요금)이 차감되므로 요청을 최소화한다.
  1. 최근 검색(/2/tweets/search/recent) 1회: 최근 24시간 한국 관련 게시물 X_SEARCH_MAX_RESULTS 개 (인기순)
     → 답글(댓글) MIN_COMMENTS 개 이상, 한국어 게시물 제외, 답글 많은 순
  2. 실제로 수집함에 넣을 게시물만 답글 검색(conversation_id:...) 1회씩
  3. 사이트 전체를 X_INTERVAL_HOURS 마다 한 번만 검색 (수집기는 3시간마다 돌아도 X 는 건너뜀)
"""
import logging
import re
from datetime import datetime, timedelta, timezone

from .classify import classify
from .fetchers import COMMENT_LIMIT, TIMEOUT, Item, clean_text, mostly_korean

log = logging.getLogger(__name__)

API = "https://api.x.com/2"
SITE = "x"

# 한국 관련 다국어 검색어. 리포스트·답글·한국어 게시물 제외 (검색어는 최대 512자)
QUERY = (
    '(Korea OR Korean OR "South Korea" OR Seoul OR kpop OR kdrama OR 韓国 OR 韩国 OR 韓國 '
    'OR "Corea del Sur" OR "Coreia do Sul" OR Südkorea OR "Corée du Sud") '
    "-is:retweet -is:reply -lang:ko"
)
TWEET_FIELDS = "created_at,public_metrics,lang,conversation_id,attachments,author_id"


class XError(Exception):
    def __init__(self, message, fatal=False):
        super().__init__(message)
        self.fatal = fatal


def _get(session, cfg, path, **params):
    headers = {"Authorization": f"Bearer {cfg['X_BEARER_TOKEN']}"}
    resp = session.get(f"{API}/{path}", params=params, headers=headers, timeout=TIMEOUT)
    if resp.status_code == 200:
        return resp.json()
    try:
        body = resp.json()
        detail = body.get("detail") or body.get("title") or str(body)[:200]
    except Exception:
        detail = resp.text[:200]
    if resp.status_code == 401:
        raise XError("X API 토큰이 올바르지 않습니다 (X_BEARER_TOKEN 확인).", fatal=True)
    if resp.status_code == 403:
        raise XError(f"X API 권한이 없습니다. 요금제가 게시물 검색을 지원하는지 확인하세요 ({detail})", fatal=True)
    if resp.status_code == 429:
        raise XError(f"X API 사용량 한도에 걸렸습니다 ({detail})", fatal=True)
    raise XError(f"X API 오류 {resp.status_code}: {detail}")


def _users_and_media(data):
    inc = data.get("includes") or {}
    users = {u["id"]: u for u in inc.get("users", [])}
    media = {m["media_key"]: m for m in inc.get("media", [])}
    return users, media


def _parse_time(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except (AttributeError, ValueError):
        return None


def _image(tweet, media):
    for key in (tweet.get("attachments") or {}).get("media_keys", []):
        m = media.get(key) or {}
        url = m.get("url") or m.get("preview_image_url")
        if url:
            return url
    return None


def _strip_mentions(text):
    """답글 앞에 붙는 @아이디 목록 제거."""
    return re.sub(r"^(?:@\w+\s+)+", "", text or "").strip()


def search_candidates(cfg, session, errors):
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        data = _get(
            session, cfg, "tweets/search/recent", query=QUERY, start_time=since, sort_order="relevancy",
            max_results=max(10, min(cfg["X_SEARCH_MAX_RESULTS"], 100)), **{
                "tweet.fields": TWEET_FIELDS, "expansions": "author_id,attachments.media_keys",
                "user.fields": "username,name", "media.fields": "url,preview_image_url,type",
            })
    except XError as exc:
        errors.append(f"X: {exc}")
        return []
    users, media = _users_and_media(data)
    candidates = []
    for t in data.get("data", []):
        replies = (t.get("public_metrics") or {}).get("reply_count", 0)
        text = clean_text(t.get("text"))
        if replies < cfg["MIN_COMMENTS"] or (t.get("lang") or "").startswith("ko") or mostly_korean(text):
            continue
        user = users.get(t.get("author_id")) or {}
        username = user.get("username") or "i"
        candidates.append(Item(
            site=SITE, external_id=t["id"], title=clean_text(text, 200), url=f"https://x.com/{username}/status/{t['id']}",
            country=SITE, lang=(t.get("lang") or "")[:10], summary=text,
            source_name=f"@{username}" + (f" ({user['name']})" if user.get("name") else ""),
            category=classify(text), published_at=_parse_time(t.get("created_at")), image_url=_image(t, media),
            num_comments=replies,
        ))
    candidates.sort(key=lambda i: i.num_comments, reverse=True)
    return candidates


def fetch_comments(cfg, session, item):
    """답글 검색 1회 (최대 X_REPLIES_PER_ITEM 개, API 최소 10). 좋아요 많은 순으로 정렬."""
    data = _get(
        session, cfg, "tweets/search/recent", query=f"conversation_id:{item.external_id} is:reply -is:retweet",
        max_results=max(10, min(cfg["X_REPLIES_PER_ITEM"], 100)), sort_order="relevancy", **{
            "tweet.fields": "public_metrics,author_id,lang", "expansions": "author_id", "user.fields": "username",
        })
    users, _ = _users_and_media(data)
    out = []
    for t in data.get("data", []):
        body = clean_text(_strip_mentions(t.get("text")), COMMENT_LIMIT)
        if not body:
            continue
        user = users.get(t.get("author_id")) or {}
        out.append(dict(author="@" + (user.get("username") or "unknown"), body=body,
                        score=(t.get("public_metrics") or {}).get("like_count", 0)))
    out.sort(key=lambda c: c["score"], reverse=True)
    return out
