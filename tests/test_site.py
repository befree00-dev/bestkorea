import pytest

from app.extensions import db
from app.models import CollectedItem, Comment, Post, Reaction, ReporterApplication, User

from .conftest import login


def make_user(username, role="member", email=None):
    u = User(username=username, email=email or f"{username}@example.com", role=role)
    u.set_password("password123")
    db.session.add(u)
    db.session.commit()
    return u


def make_post(**kw):
    p = Post(board=kw.pop("board", "free"), title=kw.pop("title", "hello"), body=kw.pop("body", "body"), **kw)
    db.session.add(p)
    db.session.commit()
    return p


def signup(client, username, email):
    return client.post("/signup", data=dict(username=username, email=email, password="password123",
                                            password2="password123", agree="y"), follow_redirects=True)


# ------------------------------------------------------------------ 읽기
def test_anonymous_can_read_everything(client, user):
    p = make_post(board="politics", title="외신이 본 한국", user_id=user.id)
    for url in ["/", "/news", "/b/politics", f"/b/politics/{p.id}", "/search?q=한국", "/privacy", "/terms"]:
        assert client.get(url).status_code == 200, url
    assert "외신이 본 한국" in client.get("/b/politics").get_data(as_text=True)


def test_anonymous_cannot_write_or_comment(client, user):
    p = make_post(user_id=user.id)
    assert client.get("/write").status_code == 302
    r = client.post(f"/post/{p.id}/comment", data={"body": "hi"})
    assert "/login" in r.headers["Location"]
    assert Comment.query.count() == 0


# ------------------------------------------------------------------ 등급과 게시 권한
def test_first_signup_is_single_admin(client):
    signup(client, "관리자", "A@Example.com")
    client.post("/logout")
    signup(client, "second", "b@example.com")
    assert User.query.filter_by(email="a@example.com").one().role == "admin"
    assert User.query.filter_by(email="b@example.com").one().role == "member"


def test_admin_email_controls_admin(app, client):
    app.config.update(ADMIN_EMAIL="boss@example.com")
    signup(client, "first", "first@example.com")
    client.post("/logout")
    signup(client, "boss", "Boss@Example.com")
    assert User.query.filter_by(username="first").one().role == "member"
    assert User.query.filter_by(username="boss").one().role == "admin"


@pytest.mark.parametrize("role,news_ok", [
    ("member", False), ("reporter", True), ("operator", True), ("admin", True),
])
def test_board_permissions_by_role(client, role, news_ok):
    make_user("u", role)
    login(client, "u@example.com")
    r = client.post("/write", data=dict(board="politics", title="해외 반응 글", body="본문", country="jp"))
    assert (Post.query.filter_by(board="politics").count() == 1) is news_ok
    if not news_ok:
        assert r.status_code == 200  # 선택지에 없는 게시판 → 폼 오류
    # 커뮤니티 게시판은 모든 등급 가능
    client.post("/write", data=dict(board="humor", title="웃긴 글", body="ㅋㅋ"))
    assert Post.query.filter_by(board="humor").count() == 1


def test_member_write_form_hides_news_boards(client):
    make_user("m")
    login(client, "m@example.com")
    html = client.get("/write").get_data(as_text=True)
    assert 'value="humor"' in html and 'value="politics"' not in html
    assert "해외 반응 글 정보" not in html
    # 해외 반응 게시판 목록에는 글쓰기 대신 기자 지원 버튼
    assert "기자 지원하기" in client.get("/b/politics").get_data(as_text=True)


def test_reporter_can_write_and_comment(client):
    make_user("r", "reporter")
    login(client, "r@example.com")
    client.post("/write", data=dict(board="economy", title="경제 기사", body="본문",
                                    source_url="https://news.example/x", country="na",
                                    image_url="https://img.example/x.jpg"))
    p = Post.query.filter_by(board="economy").one()
    assert (p.source_url, p.country, p.image_url) == ("https://news.example/x", "na", "https://img.example/x.jpg")
    client.post(f"/post/{p.id}/comment", data={"body": "좋은 기사"})
    html = client.get(f"/b/economy/{p.id}").get_data(as_text=True)
    assert '<span class="role role-reporter">기자</span>' in html


def test_cannot_edit_others_post_but_admin_can(client):
    owner = make_user("owner", "reporter")
    make_user("other", "reporter")
    p = make_post(board="politics", user_id=owner.id)
    login(client, "other@example.com")
    assert client.get(f"/post/{p.id}/edit").status_code == 403
    assert client.post(f"/post/{p.id}/delete").status_code == 403
    client.post("/logout")
    make_user("boss", "admin")
    login(client, "boss@example.com")
    assert client.post(f"/post/{p.id}/delete").status_code == 302


def test_comment_and_like(client, user):
    p = make_post(user_id=user.id)
    login(client)
    client.post(f"/post/{p.id}/comment", data={"body": "좋은 글"})
    assert Comment.query.count() == 1 and db.session.get(Post, p.id).comment_count == 1
    client.post(f"/post/{p.id}/like")
    assert db.session.get(Post, p.id).like_count == 1
    client.post(f"/post/{p.id}/like")
    assert db.session.get(Post, p.id).like_count == 0


# ------------------------------------------------------------------ 기자 지원 → 관리자 승인
def test_reporter_application_flow(client):
    member = make_user("m")
    make_user("boss", "admin")
    login(client, "m@example.com")
    client.post("/reporter/apply", data={"message": "일본 언론을 매일 읽습니다. 일본 반응 기사를 쓰고 싶어요."})
    client.post("/reporter/apply", data={"message": "중복 지원은 막혀야 합니다. 두 번째 지원서입니다."})
    assert ReporterApplication.query.count() == 1
    assert "검토 중" in client.get("/reporter/apply").get_data(as_text=True)
    client.post("/logout")

    login(client, "boss@example.com")
    html = client.get("/admin/").get_data(as_text=True)
    assert "일본 언론을 매일" in html
    a = ReporterApplication.query.one()
    client.post(f"/admin/application/{a.id}/approve")
    assert db.session.get(User, member.id).role == "reporter"
    assert db.session.get(ReporterApplication, a.id).status == "approved"


def test_admin_sets_roles_but_not_admin(client):
    make_user("boss", "admin")
    target = make_user("t")
    login(client, "boss@example.com")
    client.post(f"/admin/user/{target.id}/role", data={"role": "operator"})
    assert db.session.get(User, target.id).role == "operator"
    assert client.post(f"/admin/user/{target.id}/role", data={"role": "admin"}).status_code == 400
    assert db.session.get(User, target.id).role == "operator"


def test_only_admin_reaches_admin_and_only_staff_reach_desk(client):
    for name, role in [("m", "member"), ("r", "reporter"), ("o", "operator"), ("a", "admin")]:
        make_user(name, role)
    expected = {"m": (403, 403), "r": (403, 403), "o": (403, 200), "a": (200, 200)}
    for name, (admin_code, desk_code) in expected.items():
        login(client, f"{name}@example.com")
        assert client.get("/admin/").status_code == admin_code, name
        assert client.get("/desk/").status_code == desk_code, name
        client.post("/logout")


def test_cli_make_admin_transfers(app):
    old = make_user("old", "admin")
    new = make_user("new")
    result = app.test_cli_runner().invoke(args=["make-admin", "new@example.com"])
    assert result.exit_code == 0
    assert db.session.get(User, new.id).role == "admin"
    assert db.session.get(User, old.id).role == "operator"
    assert User.query.filter_by(role="admin").count() == 1


# ------------------------------------------------------------------ 수집함 → 게시
def _translated_item():
    item = CollectedItem(
        source_type="reddit", url="https://www.reddit.com/r/korea/comments/abc/x/", title="Seoul subway is amazing",
        source_name="r/korea", country="na", lang="en", category_hint="fun",
        comments=[{"author": "alice", "body": "Totally agree!", "score": 120},
                  {"author": "bob", "body": "Best transit", "score": 80}],
        num_comments=42, translate_status="done", title_ko="서울 지하철은 놀랍다",
        summary_ko="요약입니다.", category_ko="politics", comments_ko=["완전 동의!", "최고의 대중교통"],
        image_url="https://i.redd.it/x.jpg",
    )
    db.session.add(item)
    db.session.commit()
    return item


def test_publish_from_desk_item(client):
    make_user("o", "operator")
    item = _translated_item()
    login(client, "o@example.com")
    html = client.get(f"/write?from_item={item.id}").get_data(as_text=True)
    assert "서울 지하철은 놀랍다" in html and "요약입니다." in html and "현지 반응" in html
    assert "<summary>원문</summary>" not in client.get(f"/desk/{item.id}").get_data(as_text=True)
    r = client.post("/write", data=dict(board="politics", title="서울 지하철은 놀랍다", body="요약입니다.",
                                        source_url=item.url, country="na", image_url=item.image_url,
                                        from_item=str(item.id)))
    post = Post.query.one()
    assert r.status_code == 302 and post.original_title == "Seoul subway is amazing"
    assert [(x.body, x.body_ko) for x in post.reactions] == [("Totally agree!", "완전 동의!"), ("Best transit", "최고의 대중교통")]
    item = db.session.get(CollectedItem, item.id)
    assert item.status == "published" and item.post_id == post.id
    page = client.get(f"/b/politics/{post.id}").get_data(as_text=True)
    assert "완전 동의!" in page and "현지 반응" in page
    assert "<summary>원문</summary>" not in page and "Totally agree!" not in page  # 번역문만, 원문 보기 없음


def test_reporter_cannot_use_desk_item(client):
    make_user("r", "reporter")
    item = _translated_item()
    login(client, "r@example.com")
    assert client.get(f"/write?from_item={item.id}").status_code == 403
    assert client.get(f"/desk/{item.id}").status_code == 403
    assert Reaction.query.count() == 0


# ------------------------------------------------------------------ 보안·기타
def test_user_html_is_escaped_and_links_autolinked(client, user):
    p = make_post(body='<script>alert(1)</script> see https://example.com/a?b=1&c=2', user_id=user.id)
    html = client.get(f"/b/free/{p.id}").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert 'href="https://example.com/a?b=1&amp;c=2"' in html


def test_open_redirect_blocked(client, user):
    r = client.post("/login?next=//evil.com", data={"email": "t@example.com", "password": "password123"})
    assert r.headers["Location"] == "/"


def test_banned_user_cannot_login(client, user):
    user.is_banned = True
    db.session.commit()
    assert "이용이 제한된" in login(client).get_data(as_text=True)


def test_adsense_tags(app, client):
    assert client.get("/ads.txt").status_code == 404
    app.config.update(ADSENSE_CLIENT="ca-pub-123", ADSENSE_SLOT_TOP="999")
    assert client.get("/ads.txt").get_data(as_text=True).startswith("google.com, pub-123, DIRECT")
    html = client.get("/").get_data(as_text=True)
    assert "adsbygoogle.js?client=ca-pub-123" in html and 'data-ad-slot="999"' in html


def test_sitemap_and_country_filter(client, user):
    make_post(board="politics", title="JP글", country="jp", user_id=user.id)
    make_post(board="politics", title="US글", country="na", user_id=user.id)
    assert "/b/politics/" in client.get("/sitemap.xml").get_data(as_text=True)
    html = client.get("/news?country=jp").get_data(as_text=True)
    assert "JP글" in html and "US글" not in html


def test_database_url_normalized(monkeypatch):
    import config

    for raw in ("postgres://u:p@h:5432/db", "postgresql://u:p@h:5432/db"):
        monkeypatch.setenv("DATABASE_URL", raw)
        assert config._database_url() == "postgresql+psycopg://u:p@h:5432/db"


def test_proxy_fix_https(app):
    from flask import request

    from app import create_app
    from config import TestConfig

    class ProxyConfig(TestConfig):
        BEHIND_PROXY = True

    proxied = create_app(ProxyConfig)
    proxied.add_url_rule("/_scheme", "scheme", lambda: request.scheme)
    resp = proxied.test_client().get("/_scheme", headers={"X-Forwarded-Proto": "https"})
    assert resp.get_data(as_text=True) == "https"


def test_post_button_visible_before_translation(client):
    make_user("o", "operator")
    item = CollectedItem(source_type="youtube", url="https://www.youtube.com/watch?v=abcdefghijk", title="Korea vlog",
                         snippet="description", country="youtube", category_hint="fun",
                         comments=[{"author": "@a", "body": "nice", "score": 1}], num_comments=12)
    db.session.add(item)
    db.session.commit()
    login(client, "o@example.com")
    html = client.get(f"/desk/{item.id}").get_data(as_text=True)
    assert html.count(f'href="/write?from_item={item.id}"') == 2  # 상단·하단 모두
    assert "게시판에 올리기 (번역 전)" in html
    page = client.get(f"/write?from_item={item.id}").get_data(as_text=True)
    assert "아직 번역하지 않은 글" in page and "Korea vlog" in page


def test_published_item_links_to_post(client):
    make_user("o", "operator")
    item = _translated_item()
    login(client, "o@example.com")
    html = client.get(f"/desk/{item.id}").get_data(as_text=True)
    assert html.count("게시판에 올리기</a>") == 2
    client.post("/write", data=dict(board="politics", title="서울 지하철", body="번역 본문", country="", from_item=str(item.id)))
    html = client.get(f"/desk/{item.id}").get_data(as_text=True)
    assert "게시된 글 보기" in html and "게시판에 올리기" not in html
    # 이미 게시된 글로 다시 글쓰기를 열면 게시글로 이동 (중복 게시 방지)
    r = client.get(f"/write?from_item={item.id}")
    assert r.status_code == 302 and "/b/politics/" in r.headers["Location"]


def test_new_categories_and_regions_listed(client):
    html = client.get("/").get_data(as_text=True)
    for name in ["정치", "경제", "연예", "스포츠", "게임", "IT", "사회", "기타"]:
        assert f">{name}</a>" in html, name
    news = client.get("/news").get_data(as_text=True)
    for name in ["북미", "일본", "중국", "동남아", "유럽", "남미", "호주", "아프리카"]:
        assert name in news, name


def test_upgrade_maps_legacy_countries(app):
    from app.upgrade import upgrade_data

    old = [make_post(board="politics", title=f"old {c}", country=c) for c in ("us", "reddit", "youtube", "jp")]
    db.session.add(CollectedItem(source_type="youtube", url="https://www.youtube.com/watch?v=abcdefghijk",
                                 title="v", country="youtube"))
    db.session.commit()
    upgrade_data()
    assert [db.session.get(Post, p.id).country for p in old] == ["na", None, None, "jp"]
    assert CollectedItem.query.one().country is None
    upgrade_data()  # 다시 실행해도 그대로
    assert [db.session.get(Post, p.id).country for p in old] == ["na", None, None, "jp"]
