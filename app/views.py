from datetime import timedelta

from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from .constants import (
    BOARDS, COMMUNITY_BOARDS, COMMUNITY_TOPICS, COUNTRIES, DEFAULT_TOPIC, LEGACY_BOARD_MAP, NEWS_BOARDS, ROLE_MEMBER,
    can_write_board,
)
from .extensions import db
from .forms import CommentForm, PostForm, ReporterApplyForm
from .models import CollectedItem, Comment, Like, Post, Reaction, ReporterApplication, utcnow

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
        slug: Post.query.filter_by(board=slug).order_by(Post.created_at.desc()).limit(16).all()
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
    if board in LEGACY_BOARD_MAP:  # 예전 유머게시판·자유게시판 주소
        new_board, topic = LEGACY_BOARD_MAP[board]
        return redirect(url_for("main.board_list", board=new_board, topic=topic), 301)
    _get_board_or_404(board)
    query = _apply_filters(Post.query.filter_by(board=board))
    topic = request.args.get("topic")
    if BOARDS[board][1] == "community" and topic in COMMUNITY_TOPICS:
        query = query.filter(Post.topic == topic)
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


# ---------------------------------------------------------------- 쓰기/수정/삭제
# 해외 반응 게시판: 관리자·운영자·기자 / 커뮤니티 게시판: 모든 회원
def _can_edit(post):
    return current_user.is_authenticated and (current_user.is_admin or post.user_id == current_user.id)


def _prepare_form(form):
    form.board.choices = [(k, v[0]) for k, v in BOARDS.items() if can_write_board(current_user, k)]
    return form


def _prefill_from_item(form, item):
    """수집함에서 번역한 글로 글쓰기 양식을 채운다."""
    board = item.category_ko or item.category_hint
    form.board.data = board if board in NEWS_BOARDS else "fun"
    form.title.data = item.title_ko or item.title
    body = item.summary_ko or item.snippet or ""
    if item.image_url and item.source_type != "youtube":  # 첫 번째 사진을 본문 맨 위에 (YouTube 는 영상이 들어감)
        body = f"![]({item.image_url})\n\n{body}".rstrip()
    form.body.data = body
    form.source_url.data = item.url if item.source_type == "reddit" else (item.resolved_url or item.url)
    form.country.data = item.country
    form.image_url.data = item.image_url or ""
    form.from_item.data = str(item.id)


def _collected_item_for(form_value):
    """from_item 값이 있으면 관리자·운영자만 사용할 수 있다."""
    if not form_value:
        return None
    if not current_user.is_staff:
        abort(403)
    item = db.session.get(CollectedItem, int(form_value)) if str(form_value).isdigit() else None
    if item is None:
        abort(404)
    return item


def _save_topic(post, form):
    if BOARDS[post.board][1] != "community":
        post.topic = None
    else:
        post.topic = form.topic.data if form.topic.data in COMMUNITY_TOPICS else DEFAULT_TOPIC


def _save_news_fields(post, form):
    if current_user.can_write_news and BOARDS[post.board][1] == "news":
        post.source_url = (form.source_url.data or "").strip() or None
        post.country = form.country.data or None
        post.image_url = (form.image_url.data or "").strip() or None
    else:
        post.source_url = post.country = post.image_url = None


# ---------------------------------------------------------------- 현지 반응(댓글) 편집기
# 글쓰기·수정 화면의 '현지 반응' 편집 칸. 각 줄: r-{i}-ref, r-{i}-author, r-{i}-text, r-{i}-score, r-{i}-delete
#   ref = "o:<수집 댓글 번호>" (수집함 댓글) / "r:<Reaction id>" (기존 반응) / "" (새로 추가)
MAX_REACTIONS = 200


def _rows_from_item(item):
    translated = item.comments_ko or []
    return [dict(ref=f"o:{i}", author=c.get("author") or "", score=c.get("score") or 0,
                 text=(translated[i] if i < len(translated) and translated[i] else c.get("body") or ""))
            for i, c in enumerate(item.comments or [])]


def _rows_from_post(post):
    return [dict(ref=f"r:{r.id}", author=r.author or "", score=r.score or 0, text=r.body_ko or r.body)
            for r in post.reactions]


def _rows_from_form():
    try:
        count = min(int(request.form.get("r_count", 0)), MAX_REACTIONS)
    except ValueError:
        count = 0
    rows = []
    for i in range(count):
        f = lambda k: (request.form.get(f"r-{i}-{k}") or "").strip()  # noqa: E731
        if f("ref") == "" and not f("text"):
            continue  # 비어 있는 새 줄
        try:
            score = max(0, int(f("score") or 0))
        except ValueError:
            score = 0
        rows.append(dict(ref=f("ref"), author=f("author")[:100], text=f("text")[:5000], score=score,
                         delete=f("delete") == "1"))
    return rows


def _apply_reactions(post, rows, item=None):
    """편집기 내용을 게시글의 현지 반응에 반영한다. 원문(body)은 서버에 있는 값만 쓴다."""
    existing = {r.id: r for r in post.reactions}
    originals = (item.comments or []) if item else []
    keep, position = set(), 0
    for row in rows:
        if row["delete"] or not row["text"]:
            continue
        ref = row["ref"]
        if ref.startswith("r:") and ref[2:].isdigit() and int(ref[2:]) in existing:
            r = existing[int(ref[2:])]
        else:
            original, source = row["text"], "manual"
            if ref.startswith("o:") and ref[2:].isdigit() and int(ref[2:]) < len(originals):
                original, source = originals[int(ref[2:])].get("body") or row["text"], item.source_type
            r = Reaction(body=original, source=source)
            post.reactions.append(r)
        r.author, r.body_ko, r.score, r.position = row["author"] or "익명", row["text"], row["score"], position
        keep.add(id(r))
        position += 1
    for r in list(post.reactions):
        if id(r) not in keep:
            post.reactions.remove(r)


@bp.route("/write", methods=["GET", "POST"])
@login_required
def write():
    form = _prepare_form(PostForm())
    item = _collected_item_for(request.values.get("from_item"))
    if item and item.status == "published" and item.post:
        flash("이미 게시된 글입니다.", "info")
        return redirect(url_for("main.post_detail", board=item.post.board, post_id=item.post.id))
    rows = _rows_from_form() if request.method == "POST" else []
    if request.method == "GET":
        if item:
            _prefill_from_item(form, item)
            rows = _rows_from_item(item)
        elif request.args.get("board") in dict(form.board.choices):
            form.board.data = request.args["board"]
            if request.args.get("topic") in COMMUNITY_TOPICS:
                form.topic.data = request.args["topic"]
    if not form.board.choices:
        abort(403)
    if form.validate_on_submit():
        if not can_write_board(current_user, form.board.data):
            abort(403)
        post = Post(board=form.board.data, title=form.title.data.strip(), body=form.body.data.strip(),
                    user_id=current_user.id)
        _save_topic(post, form)
        _save_news_fields(post, form)
        if item and BOARDS[post.board][1] == "news":
            post.original_title = item.title[:500] if (item.title_ko and item.title_ko != item.title) else None
            post.source_name = item.source_name
            post.lang = item.lang
            post.published_at = item.published_at
        if current_user.can_write_news and BOARDS[post.board][1] == "news":
            _apply_reactions(post, rows, item)
        db.session.add(post)
        db.session.flush()
        if item:
            item.status, item.post_id = "published", post.id
        db.session.commit()
        flash("게시글이 등록되었습니다.", "success")
        return redirect(url_for("main.post_detail", board=post.board, post_id=post.id))
    return render_template("board/write.html", form=form, post=None, item=item, rows=rows)


@bp.route("/post/<int:post_id>/edit", methods=["GET", "POST"])
@login_required
def edit(post_id):
    post = db.get_or_404(Post, post_id)
    if not _can_edit(post):
        abort(403)
    form = _prepare_form(PostForm(obj=post))
    if post.board not in dict(form.board.choices):  # 예: 기자 자격을 잃은 회원의 기존 해외 반응 글
        form.board.choices.insert(0, (post.board, BOARDS[post.board][0]))
    rows = _rows_from_form() if request.method == "POST" else _rows_from_post(post)
    if form.validate_on_submit():
        if form.board.data != post.board and not can_write_board(current_user, form.board.data):
            abort(403)
        post.board = form.board.data
        post.title = form.title.data.strip()
        post.body = form.body.data.strip()
        _save_topic(post, form)
        _save_news_fields(post, form)
        if current_user.can_write_news and BOARDS[post.board][1] == "news":
            _apply_reactions(post, rows)
        db.session.commit()
        flash("수정되었습니다.", "success")
        return redirect(url_for("main.post_detail", board=post.board, post_id=post.id))
    return render_template("board/write.html", form=form, post=post, item=None, rows=rows)


# ---------------------------------------------------------------- 글쓰기 미리보기
@bp.route("/preview", methods=["POST"])
@login_required
def preview():
    """글쓰기 화면의 미리보기: 실제 게시글과 같은 방식으로 본문을 그린다."""
    render = current_app.jinja_env.filters["render_body"]
    return Response(str(render(request.form.get("body", "")[:100000])), mimetype="text/html")


# ---------------------------------------------------------------- 기자 지원
@bp.route("/reporter/apply", methods=["GET", "POST"])
@login_required
def reporter_apply():
    latest = (
        ReporterApplication.query.filter_by(user_id=current_user.id)
        .order_by(ReporterApplication.id.desc()).first()
    )
    form = ReporterApplyForm()
    can_apply = current_user.role == ROLE_MEMBER and not (latest and latest.status == "pending")
    if can_apply and form.validate_on_submit():
        db.session.add(ReporterApplication(user_id=current_user.id, message=form.message.data.strip()))
        db.session.commit()
        flash("기자 지원서가 접수되었습니다. 관리자 승인 후 해외 반응 게시판에 글을 올릴 수 있습니다.", "success")
        return redirect(url_for("main.reporter_apply"))
    return render_template("pages/reporter_apply.html", form=form, latest=latest, can_apply=can_apply)


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
