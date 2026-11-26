"""수집함 입력: 운영자 브라우저에서 가져온 게시물(Reddit·YouTube·X)을 수집함(CollectedItem)에 저장한다.

자동 수집은 하지 않는다. 각 사이트가 서버의 자동 요청을 막거나 유료 API 를 요구하기 때문에,
운영자가 게시물 페이지에서 'BestKorea로 가져오기' 버튼을 눌러 직접 고른 글만 들어온다.
  - browser_import.py : 브라우저가 보낸 데이터 검증·정리
  - translate.py      : 수집함 '번역' 버튼 (본문 전체 + 댓글 번역)
"""
from ..extensions import db
from ..models import CollectedItem

SITE_NAMES = {"reddit": "Reddit", "youtube": "YouTube", "x": "X(트위터)"}


def save_item(item, article_url=None):
    """Item → CollectedItem. 같은 주소가 이미 있으면 (기존 항목, False), 새로 만들면 (새 항목, True)."""
    existing = CollectedItem.query.filter_by(url=item.url).first()
    if existing:
        return existing, False
    row = CollectedItem(
        source_type=item.site, source_id=item.external_id[:50], url=item.url, title=item.title[:500],
        snippet=item.summary or "", source_name=(item.source_name or "")[:200], country=item.country,
        lang=(item.lang or "")[:10], category_hint=item.category, image_url=item.image_url,
        num_comments=item.num_comments, comments=item.reactions, published_at=item.published_at,
        article_url=article_url,
    )
    db.session.add(row)
    db.session.commit()
    return row, True
