"""해외 한국 관련 뉴스/반응 수집기.

    flask collect            # 한 번 수집
    ENABLE_SCHEDULER=true    # 웹 서버 안에서 COLLECT_INTERVAL_MINUTES 마다 자동 수집
"""
import logging
from datetime import timedelta
from itertools import zip_longest

import requests
from flask import current_app

from ..constants import NEWS_BOARDS
from ..extensions import db
from ..models import CollectLog, Post, Reaction, utcnow
from .classify import classify
from .fetchers import RedditClient, fetch_reddit, fetch_rss
from .sources import REDDIT_SOURCES, RSS_SOURCES

log = logging.getLogger(__name__)

# 소스 설정에서 정치·사회로 고정한 Reddit 소스 (재분류 대상에서 제외)
POLITICS_SOURCE_NAMES = {
    f"r/{sub}" for src in REDDIT_SOURCES if src.get("category") == "politics" for sub in src["sub"].split("+")
}


def today_news_count():
    return Post.query.filter(
        Post.board.in_(NEWS_BOARDS), Post.user_id.is_(None), Post.created_at >= utcnow() - timedelta(days=1)
    ).count()


def _new_session(cfg):
    s = requests.Session()
    s.headers["User-Agent"] = cfg["HTTP_USER_AGENT"]
    return s


def gather(cfg, session=None, per_source=4):
    """모든 소스에서 항목을 모은다. (소스별 결과 리스트, 오류 목록) 반환."""
    session = session or _new_session(cfg)
    results, errors = [], []
    for src in RSS_SOURCES:
        try:
            results.append(fetch_rss(src, session, per_source))
        except Exception as exc:
            errors.append(f"{src['id']}: {exc}")
    reddit = RedditClient(session, cfg["REDDIT_CLIENT_ID"], cfg["REDDIT_CLIENT_SECRET"], cfg["HTTP_USER_AGENT"])
    for src in REDDIT_SOURCES:
        try:
            results.append(fetch_reddit(src, reddit, per_source, cfg["REACTIONS_PER_POST"]))
        except Exception as exc:
            errors.append(f"{src['id']}: {exc}")
    return results, errors


def _round_robin(lists):
    for group in zip_longest(*lists):
        for item in group:
            if item is not None:
                yield item


def _interleave(lists):
    """국가 → 소스 순으로 라운드로빈해서 한 번의 수집에 여러 나라가 고르게 섞이도록 한다."""
    by_country = {}
    for lst in lists:
        if lst:
            by_country.setdefault(lst[0].country, []).append(lst)
    yield from _round_robin([list(_round_robin(group)) for group in by_country.values()])


def save_item(item, cfg):
    """새 항목이면 Post로 저장하고 반환, 중복이면 None."""
    if Post.query.filter_by(source_url=item.url).first():
        return None
    title, summary = item.title, item.summary
    category = item.category
    reactions_ko = []
    if cfg["TRANSLATE_ENABLED"]:
        from .enrich import enrich

        result = enrich(item, cfg["ANTHROPIC_MODEL"])
        if result:
            title, summary = result.title_ko or title, result.summary_ko
            category = category or result.category
            reactions_ko = result.reactions_ko
    category = category or classify(f"{item.title} {item.summary}")
    if category not in NEWS_BOARDS:
        category = "fun"  # 분류 불가 → 기타

    body = summary
    if item.article_url:
        body = (body + "\n\n" if body else "") + f"관련 기사: {item.article_url}"

    post = Post(
        board=category,
        title=title[:300],
        original_title=item.title[:500] if title != item.title else None,
        body=body or "",
        source_url=item.url,
        source_name=item.source_name[:200],
        country=item.country,
        lang=item.lang,
        image_url=item.image_url,
        published_at=item.published_at,
    )
    for i, r in enumerate(item.reactions):
        post.reactions.append(
            Reaction(
                author=r["author"][:100], body=r["body"], score=r.get("score", 0),
                body_ko=reactions_ko[i] if i < len(reactions_ko) else None,
            )
        )
    db.session.add(post)
    db.session.commit()
    return post


def run_collection(session=None):
    """한 번 수집 실행. CollectLog 를 반환."""
    cfg = current_app.config
    run = CollectLog()
    db.session.add(run)
    db.session.commit()

    per_source = cfg["COLLECT_MAX_PER_SOURCE"]
    if today_news_count() < cfg["DAILY_TARGET"]:
        per_source *= 2  # 오늘 목표치 미달이면 더 많이 가져온다

    lists, errors = gather(cfg, session, per_source)
    added = skipped = 0
    for item in _interleave(lists):
        if added >= cfg["COLLECT_MAX_PER_RUN"]:
            break
        try:
            if save_item(item, cfg):
                added += 1
            else:
                skipped += 1
        except Exception as exc:
            db.session.rollback()
            errors.append(f"save {item.url}: {exc}")

    run.added, run.skipped = added, skipped
    run.errors = "\n".join(errors)[:10000]
    run.finished_at = utcnow()
    db.session.commit()
    log.info("collection finished: added=%s skipped=%s errors=%s", added, skipped, len(errors))
    return run


def reclassify_fallback_politics(dry_run=False):
    """예전 기본값 때문에 '정치·사회'로 들어간 자동 수집 기사를 '기타'로 옮긴다.

    옮기는 대상(모두 해당해야 함):
      - 자동 수집 글 (회원이 쓴 글은 그대로)
      - Claude 번역을 거치지 않은 글 (번역 시에는 Claude가 직접 정치·사회로 분류한 것이므로 유지)
      - r/worldnews 처럼 소스에서 정치·사회로 지정한 글이 아님
      - 제목·본문에 어떤 카테고리 키워드도 없음
    옮긴 Post 목록을 반환한다.
    """
    candidates = Post.query.filter(
        Post.board == "politics",
        Post.user_id.is_(None),
        Post.original_title.is_(None),
    ).all()
    moved = [
        p for p in candidates
        if p.source_name not in POLITICS_SOURCE_NAMES and classify(f"{p.title} {p.body}", default=None) is None
    ]
    if not dry_run:
        for p in moved:
            p.board = "fun"
        db.session.commit()
    return moved
