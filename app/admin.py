"""관리자(1명) 전용: 회원 등급 관리, 기자 지원 승인."""
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .constants import ASSIGNABLE_ROLES, ROLE_MEMBER, ROLE_REPORTER, ROLES
from .extensions import db
from .models import CollectedItem, Comment, Post, ReporterApplication, User, utcnow

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
    role_filter = request.args.get("role")
    users = User.query
    if role_filter in ROLES:
        users = users.filter_by(role=role_filter)
    q = (request.args.get("q") or "").strip()
    if q:
        users = users.filter(User.username.ilike(f"%{q}%") | User.email.ilike(f"%{q}%"))
    return render_template(
        "admin/dashboard.html",
        inbox_new=CollectedItem.query.filter_by(status="new").count(),
        stats=dict(users=User.query.count(), posts=Post.query.count(), comments=Comment.query.count()),
        role_counts={r: User.query.filter_by(role=r).count() for r in ROLES},
        users=users.order_by(User.id.desc()).limit(100).all(),
        applications=ReporterApplication.query.filter_by(status="pending")
        .order_by(ReporterApplication.id).all(),
        ASSIGNABLE_ROLES=ASSIGNABLE_ROLES,
        ROLES=ROLES,
    )


@bp.route("/user/<int:user_id>/role", methods=["POST"])
@admin_required
def set_role(user_id):
    user = db.get_or_404(User, user_id)
    role = request.form.get("role")
    if user.is_admin or role not in ASSIGNABLE_ROLES:  # 관리자는 1명, 관리자 권한은 넘길 수 없음(CLI 사용)
        abort(400)
    user.role = role
    if role == ROLE_REPORTER:  # 대기 중인 지원서가 있으면 승인 처리
        for app_ in ReporterApplication.query.filter_by(user_id=user.id, status="pending"):
            app_.status, app_.decided_at = "approved", utcnow()
    db.session.commit()
    flash(f"{user.username}: {ROLES[role]} 등급으로 변경했습니다.", "success")
    return redirect(request.referrer or url_for("admin.dashboard"))


@bp.route("/application/<int:app_id>/<decision>", methods=["POST"])
@admin_required
def decide_application(app_id, decision):
    application = db.get_or_404(ReporterApplication, app_id)
    if application.status != "pending" or decision not in ("approve", "reject"):
        abort(400)
    application.decided_at = utcnow()
    if decision == "approve":
        application.status = "approved"
        if application.user.role == ROLE_MEMBER:
            application.user.role = ROLE_REPORTER
        flash(f"{application.user.username} 님을 기자로 승인했습니다.", "success")
    else:
        application.status = "rejected"
        flash(f"{application.user.username} 님의 기자 지원을 반려했습니다.", "info")
    db.session.commit()
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
    return redirect(request.referrer or url_for("admin.dashboard"))
