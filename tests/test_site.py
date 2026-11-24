from app.extensions import db
from app.models import Comment, Post, User

from .conftest import login


def make_post(**kw):
    p = Post(board=kw.pop("board", "free"), title=kw.pop("title", "hello"), body=kw.pop("body", "body"), **kw)
    db.session.add(p)
    db.session.commit()
    return p


def test_anonymous_can_read_everything(client):
    p = make_post(board="politics", title="외신이 본 한국")
    for url in ["/", "/news", "/b/politics", f"/b/politics/{p.id}", "/search?q=한국", "/privacy", "/terms"]:
        assert client.get(url).status_code == 200, url
    assert "외신이 본 한국" in client.get("/b/politics").get_data(as_text=True)


def test_anonymous_cannot_write_or_comment(client):
    p = make_post()
    assert client.get("/write").status_code == 302
    r = client.post("/write", data={"board": "free", "title": "t", "body": "b"})
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    r = client.post(f"/post/{p.id}/comment", data={"body": "hi"})
    assert "/login" in r.headers["Location"]
    assert Comment.query.count() == 0
    assert "로그인</a> 또는" in client.get(f"/b/free/{p.id}").get_data(as_text=True)


def test_signup_first_user_is_admin_and_can_post(client):
    r = client.post("/signup", data=dict(username="한국사랑", email="A@Example.com", password="password123",
                                          password2="password123", agree="y"), follow_redirects=True)
    assert r.status_code == 200
    u = User.query.one()
    assert u.email == "a@example.com" and u.is_admin
    r = client.post("/write", data=dict(board="humor", title="웃긴 글", body="내용\n둘째 줄", country=""),
                    follow_redirects=True)
    assert "웃긴 글" in r.get_data(as_text=True)
    post = Post.query.filter_by(board="humor").one()
    assert post.user_id == u.id


def test_signup_validation(client, user):
    r = client.post("/signup", data=dict(username="tester", email="t@example.com", password="short",
                                          password2="x", agree="y"))
    html = r.get_data(as_text=True)
    assert "이미 사용 중인 닉네임" in html and "이미 가입된 이메일" in html
    assert User.query.count() == 1


def test_comment_and_like(client, user):
    p = make_post()
    login(client)
    client.post(f"/post/{p.id}/comment", data={"body": "좋은 글"})
    assert Comment.query.count() == 1 and db.session.get(Post, p.id).comment_count == 1
    client.post(f"/post/{p.id}/like")
    assert db.session.get(Post, p.id).like_count == 1
    client.post(f"/post/{p.id}/like")  # 토글
    assert db.session.get(Post, p.id).like_count == 0


def test_cannot_edit_others_post(client, user):
    other = User(username="other", email="o@example.com")
    other.set_password("password123")
    db.session.add(other)
    db.session.commit()
    p = make_post(user_id=other.id)
    login(client)
    assert client.get(f"/post/{p.id}/edit").status_code == 403
    assert client.post(f"/post/{p.id}/delete").status_code == 403
    collected = make_post(board="politics", source_url="https://x.test/1")
    assert client.post(f"/post/{collected.id}/delete").status_code == 403


def test_user_html_is_escaped_and_links_autolinked(client, user):
    p = make_post(body='<script>alert(1)</script> see https://example.com/a?b=1&c=2')
    html = client.get(f"/b/free/{p.id}").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert 'href="https://example.com/a?b=1&amp;c=2"' in html


def test_open_redirect_blocked(client, user):
    r = client.post("/login?next=//evil.com", data={"email": "t@example.com", "password": "password123"})
    assert r.headers["Location"] == "/"


def test_banned_user_cannot_login(client, user):
    user.is_banned = True
    db.session.commit()
    r = login(client)
    assert "이용이 제한된" in r.get_data(as_text=True)


def test_adsense_tags(app, client):
    assert client.get("/ads.txt").status_code == 404
    app.config.update(ADSENSE_CLIENT="ca-pub-123", ADSENSE_SLOT_TOP="999")
    assert client.get("/ads.txt").get_data(as_text=True).startswith("google.com, pub-123, DIRECT")
    html = client.get("/").get_data(as_text=True)
    assert "adsbygoogle.js?client=ca-pub-123" in html and 'data-ad-slot="999"' in html


def test_sitemap_and_country_filter(client):
    make_post(board="politics", title="JP글", country="jp", source_url="https://x.test/jp")
    make_post(board="politics", title="US글", country="us", source_url="https://x.test/us")
    assert "/b/politics/" in client.get("/sitemap.xml").get_data(as_text=True)
    html = client.get("/news?country=jp").get_data(as_text=True)
    assert "JP글" in html and "US글" not in html


def test_admin_dashboard_requires_admin(client, user):
    login(client)
    assert client.get("/admin/").status_code == 403
    user.is_admin = True
    db.session.commit()
    assert client.get("/admin/").status_code == 200
