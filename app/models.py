from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .constants import NEWS_ROLES, ROLE_ADMIN, ROLE_MEMBER, ROLE_OPERATOR, ROLES
from .extensions import db


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(30), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    # admin(관리자, 1명) / operator(운영자) / reporter(기자) / member(회원)
    role = db.Column(db.String(20), default=ROLE_MEMBER, nullable=False, index=True)
    is_banned = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    posts = db.relationship("Post", back_populates="author", lazy="dynamic")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):
        return not self.is_banned

    @property
    def is_admin(self):
        return self.role == ROLE_ADMIN

    @property
    def is_staff(self):
        """관리자 또는 운영자: 수집함 접근 가능."""
        return self.role in (ROLE_ADMIN, ROLE_OPERATOR)

    @property
    def can_write_news(self):
        return self.role in NEWS_ROLES

    @property
    def role_name(self):
        return ROLES.get(self.role, ROLES[ROLE_MEMBER])


class ReporterApplication(db.Model):
    """회원의 기자 지원서. 관리자가 승인하면 기자 등급이 된다."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="pending", nullable=False, index=True)  # pending/approved/rejected
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    decided_at = db.Column(db.DateTime)

    user = db.relationship("User")


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    board = db.Column(db.String(30), nullable=False, index=True)
    title = db.Column(db.String(300), nullable=False)
    body = db.Column(db.Text, default="", nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    # 해외 반응 글 메타데이터
    original_title = db.Column(db.String(500))
    source_url = db.Column(db.String(2000))
    source_name = db.Column(db.String(200))
    country = db.Column(db.String(10), index=True)
    lang = db.Column(db.String(10))
    image_url = db.Column(db.Text)
    published_at = db.Column(db.DateTime)

    views = db.Column(db.Integer, default=0, nullable=False)
    like_count = db.Column(db.Integer, default=0, nullable=False)
    comment_count = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    author = db.relationship("User", back_populates="posts")
    comments = db.relationship(
        "Comment", back_populates="post", cascade="all, delete-orphan", order_by="Comment.created_at"
    )
    reactions = db.relationship(
        "Reaction", back_populates="post", cascade="all, delete-orphan", order_by="Reaction.position"
    )

    @property
    def author_name(self):
        return self.author.username if self.author else "알 수 없음"


class Reaction(db.Model):
    """해외 현지인 반응(번역된 댓글). 수집함에서 게시글을 만들 때 함께 저장된다."""

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False, index=True)
    position = db.Column(db.Integer, default=0, nullable=False)
    author = db.Column(db.String(100))
    body = db.Column(db.Text, nullable=False)
    body_ko = db.Column(db.Text)
    score = db.Column(db.Integer, default=0)
    source = db.Column(db.String(30), default="reddit")

    post = db.relationship("Post", back_populates="reactions")


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    post = db.relationship("Post", back_populates="comments")
    author = db.relationship("User")


class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    __table_args__ = (db.UniqueConstraint("post_id", "user_id"),)


class CollectedItem(db.Model):
    """수집기가 모은 해외 뉴스/게시물. 관리자·운영자만 수집함에서 보고, 번역 후 직접 게시한다."""

    id = db.Column(db.Integer, primary_key=True)
    source_type = db.Column(db.String(20), nullable=False, index=True)  # gnews / reddit
    source_id = db.Column(db.String(50))
    url = db.Column(db.String(2000), unique=True, nullable=False)
    article_url = db.Column(db.String(2000))  # Reddit 링크 글이 가리키는 기사
    title = db.Column(db.String(500), nullable=False)
    snippet = db.Column(db.Text, default="")
    source_name = db.Column(db.String(200))
    country = db.Column(db.String(10), index=True)
    lang = db.Column(db.String(10))
    category_hint = db.Column(db.String(30))
    image_url = db.Column(db.Text)
    num_comments = db.Column(db.Integer, default=0)
    comments = db.Column(db.JSON, default=list)  # [{"author","body","score"}]
    published_at = db.Column(db.DateTime)
    collected_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)

    # 상태: new(새 글) / hidden(숨김) / published(게시됨)
    status = db.Column(db.String(20), default="new", nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id", ondelete="SET NULL"))

    # 번역: none / pending / done / error
    translate_status = db.Column(db.String(20), default="none", nullable=False)
    translate_requested_at = db.Column(db.DateTime)
    translate_error = db.Column(db.Text)
    translate_note = db.Column(db.Text)  # 예: 원문 본문을 가져오지 못해 수집된 내용만 번역
    resolved_url = db.Column(db.String(2000))  # 실제 기사 주소 (Google News 경유 주소를 푼 것)
    title_ko = db.Column(db.String(500))
    summary_ko = db.Column(db.Text)  # 본문 전체 번역 (예전 요약 기능의 컬럼 이름을 그대로 사용)
    category_ko = db.Column(db.String(30))
    comments_ko = db.Column(db.JSON)  # 원문 comments 와 같은 순서의 번역 리스트
    translated_at = db.Column(db.DateTime)

    post = db.relationship("Post")
