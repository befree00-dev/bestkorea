"""해외 한국 관련 뉴스/게시물 수집기.

수집한 글은 사이트에 바로 게시되지 않고 '수집함'(CollectedItem)에만 쌓인다.
관리자·운영자가 수집함에서 번역한 뒤 직접 게시글로 올린다.

    flask collect            # 한 번 수집
"""
import logging
from datetime import timedelta
from itertools import zip_longest

import requests
from flask import current_app

from ..extensions import db
from ..models import CollectedItem, CollectLog, utcnow
from .classify import classify
from .fetchers import RedditClient, fetch_reddit, fetch_rss
from .sources import REDDIT_SOURCES, RSS_SOURCES

log = logging.getLogger(__name__)


def today_collected_count():
    return CollectedItem.query.filter(CollectedItem.collected_at >= utcnow() - timedelta(days=1)).count()


def reddit_enabled(cfg):
    return bool(cfg.get("REDDIT_CLIENT_ID") and cfg.get("REDDIT_CLIENT_SECRET"))


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
    if not reddit_enabled(cfg):
        # Reddit 은 키 없는 요청을 차단(403)하므로 키가 있을 때만 수집
        return results, errors
    reddit = RedditClient(session, cfg["REDDIT_CLIENT_ID"], cfg["REDDIT_CLIENT_SECRET"], cfg["HTTP_USER_AGENT"])
    for src in REDDIT_SOURCES:
        try:
            results.append(
                fetch_reddit(src, reddit, per_source, cfg["COMMENTS_PER_ITEM"], cfg["MIN_COMMENTS"])
            )
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


def save_item(item):
    """새 항목이면 CollectedItem 으로 저장하고 반환, 중복이면 None."""
    if len(item.url) > 2000 or CollectedItem.query.filter_by(url=item.url).first():
        return None
    row = CollectedItem(
        source_type="reddit" if item.country == "reddit" else "gnews",
        source_id=item.source_id,
        url=item.url,
        article_url=item.article_url if item.article_url and len(item.article_url) <= 2000 else None,
        title=item.title[:500],
        snippet=item.summary or "",
        source_name=(item.source_name or "")[:200],
        country=item.country,
        lang=(item.lang or "")[:10],
        category_hint=item.category or classify(f"{item.title} {item.summary}"),
        image_url=item.image_url,
        num_comments=item.num_comments or len(item.reactions),
        comments=item.reactions,
        published_at=item.published_at,
    )
    db.session.add(row)
    db.session.commit()
    return row


def run_collection(session=None):
    """한 번 수집 실행. CollectLog 를 반환."""
    cfg = current_app.config
    run = CollectLog()
    db.session.add(run)
    db.session.commit()

    per_source = cfg["COLLECT_MAX_PER_SOURCE"]
    if today_collected_count() < cfg["DAILY_TARGET"]:
        per_source *= 2  # 오늘 목표치 미달이면 더 많이 가져온다

    lists, errors = gather(cfg, session, per_source)
    added = skipped = 0
    for item in _interleave(lists):
        if added >= cfg["COLLECT_MAX_PER_RUN"]:
            break
        try:
            if save_item(item):
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
