"""서버 시작 시 기존 데이터를 새 기준으로 옮기는 간단한 업그레이드 (여러 번 실행해도 안전).

- 출처: 예전 국가 코드(us, reddit, youtube, x, etc) → 새 지역 코드(북미) 또는 지역 미지정
- 카테고리: 예전 '정치·사회'(politics)는 그대로 '정치'가 된다. 사회 글은 운영자가 글 수정에서 '사회'로 옮기면 된다.
- 게시판: 유머게시판·자유게시판 → 커뮤니티 (분류: 유머 / 잡담). post.topic 칸이 없으면 추가
"""
from sqlalchemy import inspect, text, update

from .constants import LEGACY_BOARD_MAP, LEGACY_COUNTRY_MAP
from .extensions import db
from .models import CollectedItem, Post


def _add_missing_columns():
    """create_all 은 기존 테이블에 새 칸을 추가하지 않으므로 직접 추가한다."""
    columns = {c["name"] for c in inspect(db.engine).get_columns("post")}
    if "topic" not in columns:
        db.session.execute(text("ALTER TABLE post ADD COLUMN topic VARCHAR(20)"))
        db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_post_topic ON post (topic)"))
        db.session.commit()


def upgrade_data():
    _add_missing_columns()
    changed = 0
    for old, (board, topic) in LEGACY_BOARD_MAP.items():
        result = db.session.execute(update(Post).where(Post.board == old).values(board=board, topic=topic))
        changed += result.rowcount or 0
    for model in (Post, CollectedItem):
        for old, new in LEGACY_COUNTRY_MAP.items():
            result = db.session.execute(update(model).where(model.country == old).values(country=new))
            changed += result.rowcount or 0
    db.session.commit()
    return changed
