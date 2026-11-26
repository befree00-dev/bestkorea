import logging
import os
import re
from datetime import timedelta

from flask import Flask, render_template, request, url_for
from markupsafe import Markup, escape

from config import Config

from .constants import (
    BOARDS, COMMUNITY_BOARDS, COMMUNITY_TOPICS, COUNTRIES, NEWS_BOARDS, board_name, can_write_board, country_flag,
    country_label, topic_name,
)
from .extensions import csrf, db, login_manager

_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_IMG_LINE_RE = re.compile(r"^!\[([^\]\n]{0,200})\]\(([^\s()<>\"']{1,2000})\)$")
_YT_RE = re.compile(r"https?://(?:www\.|m\.)?(?:youtube\.com/watch\?(?:.*&)?v=|youtu\.be/)([A-Za-z0-9_-]{11})")


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    os.makedirs(app.instance_path, exist_ok=True)
    if app.config.get("BEHIND_PROXY"):
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    logging.basicConfig(level=logging.INFO)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from .auth import bp as auth_bp
    from .views import bp as main_bp
    from .admin import bp as admin_bp
    from .desk import bp as desk_bp
    from .uploads import bp as uploads_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(desk_bp)
    app.register_blueprint(uploads_bp)

    _register_template_helpers(app)
    _register_errors(app)

    from .cli import register_cli

    register_cli(app)

    with app.app_context():
        db.create_all()
        from .upgrade import upgrade_data

        upgrade_data()

    return app


def _register_template_helpers(app):
    from .collector import SITE_NAMES

    @app.context_processor
    def inject_globals():
        return dict(
            BOARDS=BOARDS,
            NEWS_BOARDS=NEWS_BOARDS,
            COMMUNITY_BOARDS=COMMUNITY_BOARDS,
            COMMUNITY_TOPICS=COMMUNITY_TOPICS,
            topic_name=topic_name,
            COUNTRIES=COUNTRIES,
            board_name=board_name,
            country_label=country_label,
            country_flag=country_flag,
            SITE_NAMES=SITE_NAMES,
            cfg=app.config,
            url_with=url_with,
            can_write_board=can_write_board,
        )

    def url_with(**overrides):
        """현재 페이지 URL에서 쿼리 파라미터만 바꾼 URL. 값이 None이면 해당 파라미터 제거."""
        args = dict(request.view_args or {})
        args.update(request.args.to_dict())
        for k, v in overrides.items():
            if v is None:
                args.pop(k, None)
            else:
                args[k] = v
        return url_for(request.endpoint, **args)

    @app.template_filter("timeago")
    def timeago(dt):
        if not dt:
            return ""
        from .models import utcnow

        diff = utcnow() - dt
        if diff < timedelta(minutes=1):
            return "방금 전"
        if diff < timedelta(hours=1):
            return f"{int(diff.total_seconds() // 60)}분 전"
        if diff < timedelta(days=1):
            return f"{int(diff.total_seconds() // 3600)}시간 전"
        if diff < timedelta(days=7):
            return f"{diff.days}일 전"
        return dt.strftime("%Y.%m.%d")

    @app.template_filter("youtube_id")
    def youtube_id(url):
        m = _YT_RE.match(url or "")
        return m.group(1) if m else None

    @app.template_filter("render_body")
    def render_body(text):
        """게시글 본문: '![설명](주소)' 한 줄은 이미지로, 나머지는 nl2br 과 같이 처리.
        이미지 주소는 이 사이트 업로드(/uploads/...)나 https 주소만 허용."""
        parts, buf = [], []

        def flush():
            if buf:
                parts.append(str(nl2br("\n".join(buf))))
                buf.clear()

        for line in (text or "").split("\n"):
            m = _IMG_LINE_RE.match(line.strip())
            if m and (m.group(2).startswith("/uploads/") or m.group(2).startswith("https://")):
                flush()
                alt, src = escape(m.group(1)), escape(m.group(2))
                parts.append(f'<figure class="body-image"><img src="{src}" alt="{alt}" loading="lazy" '
                             f'referrerpolicy="no-referrer"></figure>')
            else:
                buf.append(line)
        flush()
        return Markup("".join(parts))

    @app.template_filter("body_text")
    def body_text(text):
        """미리보기·검색 설명용: 이미지 줄을 뺀 본문."""
        return "\n".join(l for l in (text or "").split("\n") if not _IMG_LINE_RE.match(l.strip()))

    @app.template_filter("nl2br")
    def nl2br(text):
        """평문을 이스케이프한 뒤 URL은 링크로, 줄바꿈은 <br>로 변환 (사용자 HTML은 허용하지 않음)."""
        escaped = str(escape(text or ""))
        linked = _URL_RE.sub(
            lambda m: f'<a href="{m.group(0)}" target="_blank" rel="nofollow noopener ugc">{m.group(0)}</a>', escaped
        )
        return Markup("<br>".join(linked.split("\n")))


def _register_errors(app):
    @app.errorhandler(404)
    def not_found(e):
        return render_template("pages/error.html", code=404, message="페이지를 찾을 수 없습니다."), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("pages/error.html", code=403, message="권한이 없습니다."), 403
