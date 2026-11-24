"""외부 소스에서 항목을 가져오는 함수들. 네트워크는 주입된 requests.Session 으로만 사용합니다."""
import html
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import feedparser

log = logging.getLogger(__name__)

TIMEOUT = 15
SUMMARY_LIMIT = 300  # 저작권 보호: 원문 전문이 아닌 짧은 발췌만 저장
REACTION_LIMIT = 1000


@dataclass
class Item:
    source_id: str
    title: str
    url: str
    country: str
    lang: str
    summary: str = ""
    source_name: str = ""
    category: str | None = None
    published_at: datetime | None = None
    image_url: str | None = None
    article_url: str | None = None  # Reddit 글이 링크한 외부 기사
    reactions: list = field(default_factory=list)  # [{"author","body","score"}]


def clean_text(raw, limit=None):
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _struct_to_dt(st):
    if not st:
        return None
    return datetime.fromtimestamp(time.mktime(st), tz=timezone.utc).replace(tzinfo=None)


# ------------------------------------------------------------------ RSS (Google News 등)
def fetch_rss(source, session, limit):
    resp = session.get(source["url"], timeout=TIMEOUT)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    items = []
    for entry in feed.entries[: limit * 3]:
        title = clean_text(entry.get("title"))
        source_name = ""
        src = entry.get("source")
        if src and src.get("title"):
            source_name = src["title"]
            suffix = f" - {source_name}"
            if title.endswith(suffix):
                title = title[: -len(suffix)]
        link = entry.get("link")
        if not title or not link:
            continue
        summary = clean_text(entry.get("summary"), SUMMARY_LIMIT)
        # Google News 요약은 제목+매체명 반복이 대부분 → 의미 없으면 비움
        if summary.startswith(title[:30]):
            summary = ""
        items.append(
            Item(
                source_id=source["id"],
                title=title,
                url=link,
                country=source["country"],
                lang=source["lang"],
                summary=summary,
                source_name=source_name or feed.feed.get("title", ""),
                category=source.get("category"),
                published_at=_struct_to_dt(entry.get("published_parsed")),
            )
        )
        if len(items) >= limit:
            break
    return items


# ------------------------------------------------------------------ Reddit
class RedditClient:
    """OAuth(client credentials) 키가 있으면 oauth.reddit.com, 없으면 공개 JSON 엔드포인트 사용."""

    def __init__(self, session, client_id="", client_secret="", user_agent="web:bestkorea-collector:1.0"):
        self.session = session
        self.client_id = client_id
        self.client_secret = client_secret
        self.session.headers.setdefault("User-Agent", user_agent)
        self._token = None
        self.base = "https://www.reddit.com"

    def _auth(self):
        if not self.client_id or self._token:
            return
        resp = self.session.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(self.client_id, self.client_secret),
            data={"grant_type": "client_credentials"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        self.session.headers["Authorization"] = f"bearer {self._token}"
        self.base = "https://oauth.reddit.com"

    def get(self, path, **params):
        self._auth()
        params.setdefault("raw_json", 1)
        resp = self.session.get(f"{self.base}{path}", params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()


def _reddit_image(data):
    url = data.get("url_overridden_by_dest") or data.get("url") or ""
    if re.search(r"\.(jpe?g|png|gif|webp)$", url, re.I):
        return url
    try:
        return html.unescape(data["preview"]["images"][0]["source"]["url"])
    except (KeyError, IndexError, TypeError):
        return None


def fetch_reddit(source, client, limit, reactions_per_post=8, min_score=20):
    if source["mode"] == "search":
        listing = client.get(
            f"/r/{source['sub']}/search.json",
            q=source["query"], restrict_sr=1, sort="top", t="day", limit=limit * 3,
        )
    else:
        listing = client.get(f"/r/{source['sub']}/{source['mode']}.json", t="day", limit=limit * 3)

    items = []
    for child in listing.get("data", {}).get("children", []):
        d = child.get("data", {})
        if d.get("stickied") or d.get("over_18") or d.get("score", 0) < min_score:
            continue
        permalink = "https://www.reddit.com" + d["permalink"]
        external = None if d.get("is_self") else (d.get("url_overridden_by_dest") or d.get("url"))
        image = _reddit_image(d)
        if external and ("reddit.com" in external or "redd.it" in external or external == image):
            external = None
        item = Item(
            source_id=source["id"],
            title=clean_text(d.get("title")),
            url=permalink,
            country="reddit",
            lang="en",
            summary=clean_text(d.get("selftext"), SUMMARY_LIMIT * 3),
            source_name=f"r/{d.get('subreddit', source['sub'])}",
            category=source.get("category"),
            published_at=datetime.fromtimestamp(d.get("created_utc", time.time()), tz=timezone.utc).replace(
                tzinfo=None
            ),
            image_url=image,
            article_url=external,
        )
        try:
            item.reactions = fetch_reddit_comments(client, d["subreddit"], d["id"], reactions_per_post)
        except Exception as exc:  # 댓글 실패해도 글은 저장
            log.warning("reddit comments failed for %s: %s", d.get("id"), exc)
        items.append(item)
        if len(items) >= limit:
            break
    return items


def fetch_reddit_comments(client, subreddit, post_id, limit):
    data = client.get(f"/r/{subreddit}/comments/{post_id}.json", sort="top", limit=limit * 2, depth=1)
    if not isinstance(data, list) or len(data) < 2:
        return []
    out = []
    for child in data[1].get("data", {}).get("children", []):
        if child.get("kind") != "t1":
            continue
        c = child["data"]
        body = (c.get("body") or "").strip()
        if not body or body in ("[deleted]", "[removed]") or c.get("stickied"):
            continue
        if (c.get("author") or "").lower() == "automoderator":
            continue
        out.append(
            dict(author=c.get("author") or "unknown", body=clean_text(body, REACTION_LIMIT), score=c.get("score", 0))
        )
        if len(out) >= limit:
            break
    return out
