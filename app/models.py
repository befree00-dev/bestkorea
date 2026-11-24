from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(30), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
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


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    board = db.Column(db.String(30), nullable=False, index=True)
    title = db.Column(db.String(300), nullable=False)
    body = db.Column(db.Text, default="", nullable=False)  # 회원 글 본문(평문) 또는 수집 기사 요약
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)  # None = 자동 수집

    # 해외 뉴스 메타데이터
    original_title = db.Column(db.String(500))
    source_url = db.Column(db.String(2000), unique=True)
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
        "Reaction", back_populates="post", cascade="all, delete-orphan", order_by="Reaction.score.desc()"
    )

    @property
    def is_collected(self):
        return self.user_id is None

    @property
    def author_name(self):
        return self.author.username if self.author else "BestKorea 봇"


class Reaction(db.Model):
    """해외 현지인 반응(예: Reddit 댓글)."""

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False, index=True)
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


class CollectLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    started_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    finished_at = db.Column(db.DateTime)
    added = db.Column(db.Integer, default=0)
    skipped = db.Column(db.Integer, default=0)
    errors = db.Column(db.Text, default="")
