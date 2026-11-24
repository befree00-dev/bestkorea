from datetime import timedelta

from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from .constants import BOARDS, COMMUNITY_BOARDS, COUNTRIES, NEWS_BOARDS
from .extensions import db
from .forms import CommentForm, PostForm
from .models import Comment, Like, Post, utcnow

bp = Blueprint("main", __name__)


def _get_board_or_404(slug):
    if slug not in BOARDS:
        abort(404)
    return slug


def _paginate(query):
    page = request.args.get("page", 1, type=int)
    return query.paginate(page=page, per_page=current_app.config["POSTS_PER_PAGE"], error_out=False)


def _apply_filters(query):
    country = request.args.get("country")
    if country in COUNTRIES:
        query = query.filter(Post.country == country)
    q = (request.args.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Post.title.ilike(like), Post.body.ilike(like), Post.original_title.ilike(like)))
    return query


# ---------------------------------------------------------------- 목록
@bp.route("/")
def index():
    since = utcnow() - timedelta(days=1)
    today_count = Post.query.filter(Post.board.in_(NEWS_BOARDS), Post.created_at >= since).count()
    latest_news = (
        Post.query.filter(Post.board.in_(NEWS_BOARDS)).order_by(Post.created_at.desc()).limit(20).all()
    )
    by_board = {
        slug: Post.query.filter_by(board=slug).order_by(Post.created_at.desc()).limit(8).all()
        for slug in COMMUNITY_BOARDS
    }
    week = utcnow() - timedelta(days=7)
    popular = (
        Post.query.filter(Post.created_at >= week)
        .order_by((Post.like_count * 10 + Post.views + Post.comment_count * 5).desc())
        .limit(10)
        .all()
    )
    return render_template(
        "index.html", latest_news=latest_news, by_board=by_board, popular=popular, today_count=today_count
    )


@bp.route("/news")
def news():
    query = _apply_filters(Post.query.filter(Post.board.in_(NEWS_BOARDS)))
    pagination = _paginate(query.order_by(Post.created_at.desc()))
    return render_template("board/list.html", board=None, pagination=pagination, title="해외 반응 전체")


@bp.route("/search")
def search():
    query = _apply_filters(Post.query)
    pagination = _paginate(query.order_by(Post.created_at.desc()))
    return render_template(
        "board/list.html", board=None, pagination=pagination, title=f"검색: {request.args.get('q', '')}"
    )


@bp.route("/b/<board>")
def board_list(board):
    _get_board_or_404(board)
    query = _apply_filters(Post.query.filter_by(board=board))
    sort = request.args.get("sort")
    order = Post.like_count.desc() if sort == "best" else Post.created_at.desc()
    pagination = _paginate(query.order_by(order, Post.id.desc()))
    return render_template("board/list.html", board=board, pagination=pagination, title=BOARDS[board][0])


# ---------------------------------------------------------------- 상세
@bp.route("/b/<board>/<int:post_id>")
def post_detail(board, post_id):
    post = db.get_or_404(Post, post_id)
    if post.board != board:
        return redirect(url_for("main.post_detail", board=post.board, post_id=post.id), 301)
    Post.query.filter_by(id=post.id).update({Post.views: Post.views + 1})
    db.session.commit()
    liked = bool(
        current_user.is_authenticated and Like.query.filter_by(post_id=post.id, user_id=current_user.id).first()
    )
    related = (
        Post.query.filter(Post.board == post.board, Post.id != post.id)
        .order_by(Post.created_at.desc())
        .limit(8)
        .all()
    )
    return render_template(
        "board/detail.html", post=post, form=CommentForm(), liked=liked, related=related, board=post.board
    )


# ---------------------------------------------------------------- 쓰기/수정/삭제 (회원 전용)
def _can_edit(post):
    return current_user.is_authenticated and (current_user.is_admin or post.user_id == current_user.id)


@bp.route("/write", methods=["GET", "POST"])
@login_required
def write():
    form = PostForm()
    if request.method == "GET" and request.args.get("board") in BOARDS:
        form.board.data = request.args["board"]
    if form.validate_on_submit():
        url = (form.source_url.data or "").strip() or None
        if url and Post.query.filter_by(source_url=url).first():
            flash("이미 등록된 원문 링크입니다.", "warning")
            return render_template("board/write.html", form=form, post=None)
        post = Post(
            board=form.board.data,
            title=form.title.data.strip(),
            body=form.body.data.strip(),
            source_url=url,
            country=form.country.data or None,
            user_id=current_user.id,
        )
        db.session.add(post)
        db.session.commit()
        flash("게시글이 등록되었습니다.", "success")
        return redirect(url_for("main.post_detail", board=post.board, post_id=post.id))
    return render_template("board/write.html", form=form, post=None)


@bp.route("/post/<int:post_id>/edit", methods=["GET", "POST"])
@login_required
def edit(post_id):
    post = db.get_or_404(Post, post_id)
    if not _can_edit(post):
        abort(403)
    form = PostForm(obj=post)
    if form.validate_on_submit():
        post.board = form.board.data
        post.title = form.title.data.strip()
        post.body = form.body.data.strip()
        url = (form.source_url.data or "").strip() or None
        if url != post.source_url and url and Post.query.filter_by(source_url=url).first():
            flash("이미 등록된 원문 링크입니다.", "warning")
            return render_template("board/write.html", form=form, post=post)
        post.source_url = url
        post.country = form.country.data or None
        db.session.commit()
        flash("수정되었습니다.", "success")
        return redirect(url_for("main.post_detail", board=post.board, post_id=post.id))
    return render_template("board/write.html", form=form, post=post)


@bp.route("/post/<int:post_id>/delete", methods=["POST"])
@login_required
def delete(post_id):
    post = db.get_or_404(Post, post_id)
    if not _can_edit(post):
        abort(403)
    board = post.board
    Like.query.filter_by(post_id=post.id).delete()
    db.session.delete(post)
    db.session.commit()
    flash("삭제되었습니다.", "info")
    return redirect(url_for("main.board_list", board=board))


# ---------------------------------------------------------------- 댓글/추천 (회원 전용)
@bp.route("/post/<int:post_id>/comment", methods=["POST"])
@login_required
def add_comment(post_id):
    post = db.get_or_404(Post, post_id)
    form = CommentForm()
    if form.validate_on_submit():
        db.session.add(Comment(post_id=post.id, user_id=current_user.id, body=form.body.data.strip()))
        post.comment_count = (post.comment_count or 0) + 1
        db.session.commit()
    else:
        flash("댓글 내용을 입력해 주세요.", "warning")
    return redirect(url_for("main.post_detail", board=post.board, post_id=post.id) + "#comments")


@bp.route("/comment/<int:comment_id>/delete", methods=["POST"])
@login_required
def delete_comment(comment_id):
    comment = db.get_or_404(Comment, comment_id)
    if not (current_user.is_admin or comment.user_id == current_user.id):
        abort(403)
    post = comment.post
    post.comment_count = max(0, (post.comment_count or 0) - 1)
    db.session.delete(comment)
    db.session.commit()
    return redirect(url_for("main.post_detail", board=post.board, post_id=post.id) + "#comments")


@bp.route("/post/<int:post_id>/like", methods=["POST"])
@login_required
def like(post_id):
    post = db.get_or_404(Post, post_id)
    existing = Like.query.filter_by(post_id=post.id, user_id=current_user.id).first()
    if existing:
        db.session.delete(existing)
        post.like_count = max(0, post.like_count - 1)
    else:
        db.session.add(Like(post_id=post.id, user_id=current_user.id))
        post.like_count += 1
    db.session.commit()
    return redirect(url_for("main.post_detail", board=post.board, post_id=post.id))


# ---------------------------------------------------------------- 정적 페이지 / SEO / 광고
@bp.route("/about")
def about():
    return render_template("pages/about.html")


@bp.route("/privacy")
def privacy():
    return render_template("pages/privacy.html")


@bp.route("/terms")
def terms():
    return render_template("pages/terms.html")


@bp.route("/ads.txt")
def ads_txt():
    client = current_app.config["ADSENSE_CLIENT"]
    if not client:
        abort(404)
    pub = client.replace("ca-", "", 1)
    return Response(f"google.com, {pub}, DIRECT, f08c47fec0942fa0\n", mimetype="text/plain")


@bp.route("/robots.txt")
def robots_txt():
    base = current_app.config["SITE_URL"]
    body = (
        "User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /write\nDisallow: /login\nDisallow: /signup\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
    return Response(body, mimetype="text/plain")


@bp.route("/sitemap.xml")
def sitemap():
    base = current_app.config["SITE_URL"]
    posts = Post.query.order_by(Post.created_at.desc()).limit(5000).all()
    urls = [f"{base}/"] + [f"{base}/b/{b}" for b in BOARDS]
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        lines.append(f"<url><loc>{u}</loc><changefreq>hourly</changefreq></url>")
    for p in posts:
        lastmod = (p.updated_at or p.created_at).strftime("%Y-%m-%d")
        lines.append(f"<url><loc>{base}/b/{p.board}/{p.id}</loc><lastmod>{lastmod}</lastmod></url>")
    lines.append("</urlset>")
    return Response("\n".join(lines), mimetype="application/xml")
