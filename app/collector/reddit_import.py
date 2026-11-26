"""운영자가 브라우저에서 가져온 Reddit 게시글 JSON 을 수집함 항목으로 바꾼다.

Reddit 은 서버의 자동 요청을 차단하므로, 운영자의 브라우저(북마클릿)가 게시글 주소 + '.json' 을 읽어
BestKorea 로 넘겨준다. 여기서는 그 JSON 을 검증·정리만 한다 (서버는 Reddit 에 접속하지 않음).
"""
import html
import json
import re
from datetime import datetime, timezone

from .classify import classify
from .fetchers import COMMENT_LIMIT, Item, clean_text

MAX_PAYLOAD = 5 * 1024 * 1024
PERMALINK_RE = re.compile(r"^/r/[A-Za-z0-9_]+/comments/[a-z0-9]+(/[^\s?#]*)?$")


class RedditImportError(Exception):
    pass


def _image(post):
    url = post.get("url_overridden_by_dest") or post.get("url") or ""
    if re.search(r"\.(jpe?g|png|gif|webp)$", url, re.I):
        return url
    try:
        return html.unescape(post["preview"]["images"][0]["source"]["url"])
    except (KeyError, IndexError, TypeError):
        return None


def parse_reddit_json(text, min_comments, max_comments):
    """Reddit 게시글 .json 응답 → Item. 문제가 있으면 RedditImportError."""
    if not text or len(text) > MAX_PAYLOAD:
        raise RedditImportError("가져온 데이터가 비어 있거나 너무 큽니다.")
    try:
        data = json.loads(text)
        post = data[0]["data"]["children"][0]["data"]
        children = data[1]["data"]["children"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise RedditImportError("Reddit 게시글 데이터 형식이 아닙니다. 게시글 페이지에서 가져왔는지 확인하세요.")

    permalink = post.get("permalink") or ""
    if not PERMALINK_RE.match(permalink):
        raise RedditImportError("Reddit 게시글 주소를 확인할 수 없습니다.")
    if post.get("over_18"):
        raise RedditImportError("성인(NSFW) 게시글은 가져올 수 없습니다.")
    num_comments = int(post.get("num_comments") or 0)
    if num_comments < min_comments:
        raise RedditImportError(f"댓글이 {num_comments}개라 수집 기준({min_comments}개 이상)에 못 미칩니다.")

    comments = []
    for child in children:
        if child.get("kind") != "t1":
            continue
        c = child.get("data") or {}
        body = (c.get("body") or "").strip()
        author = c.get("author") or ""
        if not body or body in ("[deleted]", "[removed]") or c.get("stickied") or author.lower() == "automoderator":
            continue
        comments.append(dict(author=author or "unknown", body=clean_text(body, COMMENT_LIMIT), score=c.get("score", 0)))
    comments.sort(key=lambda c: c["score"] or 0, reverse=True)

    external = None
    if not post.get("is_self"):
        external = post.get("url_overridden_by_dest") or post.get("url")
        if external and ("reddit.com" in external or "redd.it" in external or external == _image(post)
                         or not external.startswith(("http://", "https://"))):
            external = None

    title = clean_text(post.get("title"), 300)
    selftext = clean_text(post.get("selftext"), 5000)
    created = post.get("created_utc")
    return Item(
        site="reddit", external_id=str(post.get("id", ""))[:50], title=title,
        url="https://www.reddit.com" + permalink, country="reddit", lang="en", summary=selftext,
        source_name=f"r/{post.get('subreddit', '')}", category=classify(f"{title} {selftext[:500]}"),
        published_at=datetime.fromtimestamp(created, tz=timezone.utc).replace(tzinfo=None) if created else None,
        image_url=_image(post), num_comments=num_comments, reactions=comments[:max_comments],
    ), external
