"""서버 시작 시 기존 데이터를 새 기준으로 옮기는 간단한 업그레이드 (여러 번 실행해도 안전).

- 출처: 예전 국가 코드(us, reddit, youtube, x, etc) → 새 지역 코드(북미) 또는 지역 미지정
- 카테고리: 예전 '정치·사회'(politics)는 그대로 '정치'가 된다. 사회 글은 운영자가 글 수정에서 '사회'로 옮기면 된다.
"""
from sqlalchemy import update

from .constants import LEGACY_COUNTRY_MAP
from .extensions import db
from .models import CollectedItem, Post


def upgrade_data():
    changed = 0
    for model in (Post, CollectedItem):
        for old, new in LEGACY_COUNTRY_MAP.items():
            result = db.session.execute(update(model).where(model.country == old).values(country=new))
            changed += result.rowcount or 0
    db.session.commit()
    return changed
