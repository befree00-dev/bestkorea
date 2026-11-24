"""해외 SNS·포털의 한국 관련 당일 게시물 중 댓글 많은 글을 사이트별로 수집한다.

규칙
  - 최근 24시간에 올라온 글 중 댓글 MIN_COMMENTS(기본 10)개 이상
  - 사이트별로 하루(한국 시간 기준) 댓글이 가장 많은 PER_SITE_DAILY(기본 10)개만 수집함에 유지
    수집할 때마다 댓글 수를 다시 비교해, 아직 손대지 않은 글이 더 인기 있는 글에 밀리면 교체한다
  - 수집한 글은 사이트에 바로 게시되지 않고 관리자·운영자 전용 '수집함'(CollectedItem)에만 쌓인다

    flask collect            # 한 번 수집
"""
import logging
from datetime import datetime, timedelta, timezone

import requests
from flask import current_app

from ..extensions import db
from ..models import CollectedItem, CollectLog, utcnow
from . import youtube

log = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 사이트 코드 → (이름, 사용 가능 여부 판단, 후보 검색, 댓글 가져오기)
SITES = {
    "youtube": dict(
        name="YouTube",
        enabled=lambda cfg: bool(cfg.get("YOUTUBE_API_KEY")),
        missing="YOUTUBE_API_KEY 가 설정되지 않았습니다",
        search=youtube.search_candidates,
        comments=youtube.fetch_comments,
    ),
}


def kst_midnight_utc(now=None):
    """오늘(한국 시간) 0시를 UTC naive datetime 으로."""
    now = now or datetime.now(timezone.utc)
    midnight = now.astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc).replace(tzinfo=None)


def today_counts():
    since = kst_midnight_utc()
    return {
        site: CollectedItem.query.filter(CollectedItem.source_type == site, CollectedItem.collected_at >= since).count()
        for site in SITES
    }


def site_status(cfg):
    """관리 화면 표시용: [(코드, 이름, 켜짐 여부, 안내)]"""
    return [(code, s["name"], s["enabled"](cfg), s["missing"]) for code, s in SITES.items()]


def _new_session(cfg):
    s = requests.Session()
    s.headers["User-Agent"] = cfg["HTTP_USER_AGENT"]
    return s


def _untouched(row):
    return row.status == "new" and row.translate_status == "none" and not row.post_id


def _save(item):
    row = CollectedItem(
        source_type=item.site, source_id=item.external_id[:50], url=item.url, title=item.title[:500],
        snippet=item.summary or "", source_name=(item.source_name or "")[:200], country=item.country,
        lang=(item.lang or "")[:10], category_hint=item.category, image_url=item.image_url,
        num_comments=item.num_comments, comments=item.reactions, published_at=item.published_at,
    )
    db.session.add(row)
    return row


def collect_site(code, cfg, session, errors):
    """한 사이트 수집. (추가 수, 교체로 빠진 수) 반환."""
    site = SITES[code]
    candidates = site["search"](cfg, session, errors)
    if not candidates:
        return 0, 0

    existing = {r.url: r for r in CollectedItem.query.filter(
        CollectedItem.url.in_([c.url for c in candidates])).all()}
    # 이미 수집된 글은 댓글 수만 갱신 (번역·게시 전인 경우)
    for c in candidates:
        row = existing.get(c.url)
        if row is not None and _untouched(row):
            row.num_comments = c.num_comments

    today_rows = CollectedItem.query.filter(
        CollectedItem.source_type == code, CollectedItem.collected_at >= kst_midnight_utc()).all()
    # 운영자가 이미 손댄 글(번역·숨김·게시)은 항상 남기고 하루 개수에 포함한다
    protected = [r for r in today_rows if not _untouched(r)]
    slots = max(0, cfg["PER_SITE_DAILY"] - len(protected))
    pool = [(r.num_comments or 0, "row", r) for r in today_rows if _untouched(r)]
    pool += [(c.num_comments, "new", c) for c in candidates if c.url not in existing]
    pool.sort(key=lambda x: x[0], reverse=True)
    keep = pool[:slots]
    keep_ids = {id(obj) for _, _, obj in keep}

    added = 0
    for _, kind, obj in keep:
        if kind != "new":
            continue
        try:
            obj.reactions = site["comments"](cfg, session, obj)
        except Exception as exc:  # 댓글을 못 가져와도 글은 저장
            errors.append(f"{code} 댓글 {obj.external_id}: {exc}")
        _save(obj)
        added += 1

    removed = 0
    for row in today_rows:  # 더 인기 있는 글에 밀린, 아직 손대지 않은 글은 교체
        if id(row) not in keep_ids and _untouched(row):
            db.session.delete(row)
            removed += 1
    db.session.commit()
    return added, removed


def run_collection(session=None):
    """한 번 수집 실행. CollectLog 를 반환."""
    cfg = current_app.config
    run = CollectLog()
    db.session.add(run)
    db.session.commit()
    session = session or _new_session(cfg)

    added = replaced = 0
    errors = []
    for code, site in SITES.items():
        if not site["enabled"](cfg):
            errors.append(f"{site['name']}: {site['missing']} (수집 안 함)")
            continue
        try:
            a, r = collect_site(code, cfg, session, errors)
            added, replaced = added + a, replaced + r
        except Exception as exc:
            db.session.rollback()
            errors.append(f"{site['name']}: {exc}")

    run.added, run.skipped = added, replaced
    run.errors = "\n".join(errors)[:10000]
    run.finished_at = utcnow()
    db.session.commit()
    log.info("collection finished: added=%s replaced=%s errors=%s", added, replaced, len(errors))
    return run
