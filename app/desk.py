"""수집함: 관리자·운영자 전용. 수집된 해외 뉴스/게시물을 보고, 번역하고, 게시글로 작성한다."""
from functools import wraps

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from .constants import COUNTRIES
from .extensions import db
from .models import CollectedItem

bp = Blueprint("desk", __name__, url_prefix="/desk")

STATUSES = {"new": "새 글", "published": "게시됨", "hidden": "숨김"}


def staff_required(f):
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_staff:
            abort(403)
        return f(*args, **kwargs)

    return wrapper


@bp.route("/")
@staff_required
def index():
    from .collector import SITE_NAMES

    status = request.args.get("status", "new")
    query = CollectedItem.query
    if status in STATUSES:
        query = query.filter_by(status=status)
    source = request.args.get("source")
    if source:
        query = query.filter_by(source_type=source)
    country = request.args.get("country")
    if country in COUNTRIES:
        query = query.filter_by(country=country)
    if request.args.get("translated") == "1":
        query = query.filter_by(translate_status="done")
    q = (request.args.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        query = query.filter(or_(CollectedItem.title.ilike(like), CollectedItem.title_ko.ilike(like)))
    if request.args.get("sort") == "comments":
        query = query.order_by(CollectedItem.num_comments.desc(), CollectedItem.id.desc())
    else:
        query = query.order_by(CollectedItem.collected_at.desc(), CollectedItem.num_comments.desc())
    pagination = query.paginate(
        page=request.args.get("page", 1, type=int), per_page=30, error_out=False
    )
    counts = {s: CollectedItem.query.filter_by(status=s).count() for s in STATUSES}
    return render_template(
        "desk/list.html", pagination=pagination, status=status, counts=counts, STATUSES=STATUSES,
        SITE_NAMES=SITE_NAMES,
    )


@bp.route("/<int:item_id>")
@staff_required
def item(item_id):
    from .collector.translate import is_running

    row = db.get_or_404(CollectedItem, item_id)
    return render_template("desk/item.html", item=row, running=is_running(row))


@bp.route("/<int:item_id>/translate", methods=["POST"])
@staff_required
def translate(item_id):
    from .collector.translate import start_translation

    row = db.get_or_404(CollectedItem, item_id)
    if not start_translation(row):
        flash("이미 번역 중입니다. 잠시만 기다려 주세요.", "info")
    return redirect(url_for("desk.item", item_id=row.id))


@bp.route("/<int:item_id>/status.json")
@staff_required
def status(item_id):
    row = db.get_or_404(CollectedItem, item_id)
    return jsonify(translate_status=row.translate_status)


@bp.route("/<int:item_id>/visibility", methods=["POST"])
@staff_required
def visibility(item_id):
    row = db.get_or_404(CollectedItem, item_id)
    if row.status == "published":
        abort(400)
    row.status = "hidden" if row.status == "new" else "new"
    db.session.commit()
    flash("숨겼습니다." if row.status == "hidden" else "수집함으로 되돌렸습니다.", "info")
    return redirect(request.referrer or url_for("desk.index"))


# ------------------------------------------------------------------ 브라우저에서 가져오기 (운영자 브라우저 → 수집함)
@bp.route("/import", methods=["GET", "POST"])
@bp.route("/import/reddit", methods=["GET", "POST"])  # 예전에 등록한 Reddit 전용 버튼 호환
@staff_required
def import_page():
    from .collector import SITE_NAMES, save_item
    from .collector.browser_import import ImportError_, detect, parse

    if request.method == "POST":
        cfg = current_app.config
        try:
            site, payload = request.form.get("site"), request.form.get("payload", "")
            if site not in SITE_NAMES:  # 붙여넣기: 내용으로 사이트 판별
                site, payload = detect(payload)
            item, article_url = parse(site, payload, cfg["MIN_COMMENTS"], cfg["COMMENTS_PER_ITEM"])
        except ImportError_ as exc:
            flash(str(exc), "danger")
            return redirect(url_for("desk.import_page"))
        row, created = save_item(item, article_url)
        if created:
            flash(f"{SITE_NAMES[site]} 글을 수집함에 추가했습니다 (댓글 {len(item.reactions)}개). 번역을 눌러 보세요.",
                  "success")
        else:
            flash("이미 수집함에 있는 글입니다.", "info")
        return redirect(url_for("desk.item", item_id=row.id))

    return render_template("desk/import.html", origin=request.host_url.rstrip("/"))
