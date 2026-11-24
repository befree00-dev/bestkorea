from functools import wraps

from flask import Blueprint, abort, current_app, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from .extensions import db
from .models import CollectLog, Comment, Post, User

bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)

    return wrapper


@bp.route("/")
@admin_required
def dashboard():
    from .collector import reddit_enabled, today_news_count

    return render_template(
        "admin/dashboard.html",
        logs=CollectLog.query.order_by(CollectLog.id.desc()).limit(20).all(),
        today=today_news_count(),
        reddit_on=reddit_enabled(current_app.config),
        stats=dict(
            users=User.query.count(), posts=Post.query.count(), comments=Comment.query.count(),
        ),
        users=User.query.order_by(User.id.desc()).limit(30).all(),
    )


@bp.route("/collect", methods=["POST"])
@admin_required
def collect_now():
    from .collector import run_collection

    run = run_collection()
    flash(f"수집 완료: 추가 {run.added}건, 중복 {run.skipped}건" + (" (오류 있음)" if run.errors else ""), "info")
    return redirect(url_for("admin.dashboard"))


@bp.route("/user/<int:user_id>/ban", methods=["POST"])
@admin_required
def toggle_ban(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        abort(400)
    user.is_banned = not user.is_banned
    db.session.commit()
    flash(f"{user.username}: {'이용 제한' if user.is_banned else '제한 해제'}", "info")
    return redirect(url_for("admin.dashboard"))
