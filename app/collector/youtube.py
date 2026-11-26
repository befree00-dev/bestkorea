"""YouTube Data API v3 수집기 (공식 API, YOUTUBE_API_KEY 필요).

1. search.list  : 언어별 한국 관련 검색어로 최근 24시간 영상 검색 (조회수순)
2. videos.list  : 댓글 수·언어 확인 → 댓글 MIN_COMMENTS 개 이상, 한국어 영상 제외, 댓글 많은 순
3. commentThreads.list : 실제로 수집함에 넣을 영상만 인기 댓글 가져오기
"""
import logging
from datetime import datetime, timedelta, timezone

from .classify import classify
from .fetchers import COMMENT_LIMIT, TIMEOUT, Item, clean_text, mostly_korean
from .sources import YOUTUBE_QUERIES

log = logging.getLogger(__name__)

API = "https://www.googleapis.com/youtube/v3"
SITE = "youtube"


class YouTubeError(Exception):
    def __init__(self, message, fatal=False):
        super().__init__(message)
        self.fatal = fatal  # 키 오류·할당량 소진: 이번 수집에서 더 요청해도 소용없음


def _get(session, cfg, path, **params):
    params["key"] = cfg["YOUTUBE_API_KEY"]
    resp = session.get(f"{API}/{path}", params=params, timeout=TIMEOUT)
    if resp.status_code != 200:
        try:
            err = resp.json()["error"]
            reason = (err.get("errors") or [{}])[0].get("reason", "")
            message = err.get("message", "")
        except Exception:
            reason, message = "", resp.text[:200]
        if reason == "quotaExceeded":
            raise YouTubeError("YouTube API 하루 할당량을 모두 썼습니다 (태평양 시간 자정에 초기화).", fatal=True)
        if reason in ("keyInvalid", "accessNotConfigured", "keyExpired") or "API key" in message:
            raise YouTubeError(f"YouTube API 키를 사용할 수 없습니다 ({message})", fatal=True)
        raise YouTubeError(f"YouTube API 오류 {resp.status_code} {reason}: {message}".strip())
    return resp.json()


def _parse_time(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except (AttributeError, ValueError):
        return None


def _thumbnail(snippet):
    thumbs = snippet.get("thumbnails") or {}
    for key in ("maxres", "standard", "high", "medium", "default"):
        if key in thumbs:
            return thumbs[key]["url"]
    return None


def search_candidates(cfg, session, errors):
    """댓글 MIN_COMMENTS 개 이상인 해외(비한국어) 한국 관련 영상, 댓글 많은 순."""
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids, lang_of = [], {}
    for query in YOUTUBE_QUERIES:
        try:
            data = _get(session, cfg, "search", part="snippet", q=query["q"], type="video", order="viewCount",
                        publishedAfter=since, maxResults=50, relevanceLanguage=query["relevance_language"])
        except YouTubeError as exc:
            if exc.fatal:
                errors.append(f"YouTube: {exc}")
                return []
            errors.append(f"youtube 검색 '{query['q']}': {exc}")
            continue
        for it in data.get("items", []):
            vid = (it.get("id") or {}).get("videoId")
            if vid and vid not in lang_of:
                ids.append(vid)
                lang_of[vid] = query["relevance_language"]

    candidates = []
    for start in range(0, len(ids), 50):
        try:
            data = _get(session, cfg, "videos", part="snippet,statistics", id=",".join(ids[start:start + 50]))
        except YouTubeError as exc:
            errors.append(f"youtube 영상 정보: {exc}")
            break
        for v in data.get("items", []):
            sn, st = v.get("snippet", {}), v.get("statistics", {})
            comments = int(st.get("commentCount", 0) or 0)  # 댓글 사용 중지 영상은 값이 없음
            if comments < cfg["MIN_COMMENTS"]:
                continue
            audio_lang = (sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or "").lower()
            title, description = sn.get("title", ""), sn.get("description", "")
            if audio_lang.startswith("ko") or mostly_korean(title):
                continue  # 국내(한국어) 영상은 '해외 반응'이 아니므로 제외
            candidates.append(Item(
                site=SITE, external_id=v["id"], title=clean_text(title, 300),
                url=f"https://www.youtube.com/watch?v={v['id']}", country=SITE,
                lang=(audio_lang or lang_of.get(v["id"], ""))[:10],
                summary=clean_text(description, 5000, keep_lines=True), source_name=sn.get("channelTitle", ""),
                category=classify(f"{title} {description[:500]}"),
                published_at=_parse_time(sn.get("publishedAt")), image_url=_thumbnail(sn),
                num_comments=comments,
            ))
    candidates.sort(key=lambda i: i.num_comments, reverse=True)
    return candidates


def fetch_comments(cfg, session, item):
    """인기 댓글 최대 COMMENTS_PER_ITEM 개 (YouTube 는 한 번에 최대 100개)."""
    data = _get(session, cfg, "commentThreads", part="snippet", videoId=item.external_id,
                maxResults=max(1, min(cfg["COMMENTS_PER_ITEM"], 100)), order="relevance", textFormat="plainText")
    out = []
    for thread in data.get("items", []):
        c = thread.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
        body = clean_text(c.get("textDisplay") or c.get("textOriginal"), COMMENT_LIMIT, keep_lines=True)
        if body:
            out.append(dict(author=c.get("authorDisplayName") or "unknown", body=body, score=c.get("likeCount", 0)))
    return out
