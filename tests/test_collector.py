from types import SimpleNamespace

import pytest

from app import collector
from app.collector import translate as tr
from app.collector.classify import classify
from app.collector.fetchers import RedditClient, fetch_reddit, fetch_rss
from app.extensions import db
from app.models import CollectedItem, CollectLog, Post

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Google News</title>
<item><title>Samsung shares jump on chip demand - Example Wire</title>
  <link>https://news.example/{p}/a1</link><pubDate>Mon, 23 Nov 2026 10:00:00 GMT</pubDate>
  <description>&lt;a href="x"&gt;Samsung shares jump on chip demand&lt;/a&gt;</description>
  <source url="https://wire.example">Example Wire</source></item>
<item><title>Son Heung-min scores twice - Sports Daily</title>
  <link>https://news.example/{p}/a2</link><source url="https://sd.example">Sports Daily</source></item>
<item><title>韓国の大統領が来日 - サンプル新聞</title>
  <link>https://news.example/{p}/a3</link><source url="https://jp.example">サンプル新聞</source></item>
</channel></rss>"""


def reddit_listing(prefix):
    posts = [
        dict(id=f"{prefix}1", title="Seoul subway is amazing", permalink=f"/r/korea/comments/{prefix}1/x/",
             subreddit="korea", score=500, num_comments=42, is_self=True, selftext="Just visited.",
             created_utc=1764000000),
        dict(id=f"{prefix}2", title="few comments", permalink=f"/r/korea/comments/{prefix}2/x/", subreddit="korea",
             score=900, num_comments=9, is_self=True, created_utc=1764000000),
        dict(id=f"{prefix}3", title="nsfw", permalink=f"/r/korea/comments/{prefix}3/x/", subreddit="korea",
             score=900, num_comments=99, over_18=True, created_utc=1764000000),
    ]
    return {"data": {"children": [{"kind": "t3", "data": p} for p in posts]}}


COMMENTS = [
    {},
    {"data": {"children": [
        {"kind": "t1", "data": {"author": "AutoModerator", "body": "rules", "score": 1}},
        {"kind": "t1", "data": {"author": "alice", "body": "Totally agree!", "score": 120}},
        {"kind": "t1", "data": {"author": "bob", "body": "[deleted]", "score": 3}},
        {"kind": "t1", "data": {"author": "carol", "body": "Best transit in the world", "score": 80}},
        {"kind": "more", "data": {}},
    ]}},
]


class FakeResponse:
    def __init__(self, content=b"", data=None):
        self.content, self._data = content, data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, fail=()):
        self.headers = {}
        self.calls = []
        self.fail = fail

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        if any(f in url for f in self.fail):
            raise ConnectionError("blocked")
        if "news.google.com" in url:
            return FakeResponse(RSS.replace("{p}", str(abs(hash(url)) % 10000)).encode())
        if "/comments/" in url:
            return FakeResponse(data=COMMENTS)
        return FakeResponse(data=reddit_listing(str(abs(hash(url)) % 10000)))

    def post(self, url, auth=None, data=None, timeout=None):
        self.calls.append(url)
        assert url.endswith("/api/v1/access_token") and data == {"grant_type": "client_credentials"}
        return FakeResponse(data={"access_token": "tok"})


@pytest.fixture(autouse=True)
def reddit_keys(app):
    app.config.update(REDDIT_CLIENT_ID="id", REDDIT_CLIENT_SECRET="secret")


# ------------------------------------------------------------------ 수집
def test_fetch_rss_strips_publisher_suffix():
    items = fetch_rss(dict(id="t", url="https://news.google.com/rss", country="us", lang="en"), FakeSession(), 5)
    assert [i.title for i in items][:2] == ["Samsung shares jump on chip demand", "Son Heung-min scores twice"]
    assert items[0].source_name == "Example Wire"
    assert items[0].summary == ""
    assert items[0].published_at is not None


def test_fetch_reddit_requires_10_comments():
    client = RedditClient(FakeSession())
    items = fetch_reddit(dict(id="r", sub="korea", mode="top", category=None), client, 5,
                         comments_per_item=50, min_comments=10)
    assert [i.title for i in items] == ["Seoul subway is amazing"]  # 댓글 9개 글, NSFW 제외
    assert items[0].num_comments == 42
    assert [r["author"] for r in items[0].reactions] == ["alice", "carol"]


@pytest.mark.parametrize("text,cat", [
    ("Samsung shares jump on chip demand", "economy"),
    ("Son Heung-min scores twice for Tottenham", "sports"),
    ("BLACKPINK announce world tour", "entertainment"),
    ("T1 Faker wins Worlds again", "game"),
    ("韓国の大統領が来日", "politics"),
    ("Something with no keywords", "fun"),
])
def test_classify(text, cat):
    assert classify(text) == cat


def test_collection_goes_to_inbox_not_site(app):
    app.config.update(COLLECT_MAX_PER_RUN=100)
    run = collector.run_collection(FakeSession())
    assert run.added > 10 and run.errors == ""
    assert Post.query.count() == 0  # 사이트에는 자동 게시하지 않음
    assert CollectedItem.query.count() == run.added
    reddit = CollectedItem.query.filter_by(source_type="reddit").first()
    assert reddit.num_comments == 42 and [c["author"] for c in reddit.comments] == ["alice", "carol"]
    jp = CollectedItem.query.filter(CollectedItem.url.like("%/a1"), CollectedItem.country == "jp").first()
    assert jp.source_type == "gnews" and jp.category_hint == "economy" and jp.status == "new"
    # 다시 실행해도 중복 저장 없음
    n = CollectedItem.query.count()
    assert collector.run_collection(FakeSession()).added == 0 and CollectedItem.query.count() == n
    assert CollectLog.query.count() == 2


def test_collection_cap_errors_and_mix(app):
    app.config.update(COLLECT_MAX_PER_RUN=6)
    run = collector.run_collection(FakeSession(fail=("reddit.com/r/kpop",)))
    assert run.added == 6 and "rd-kpop" in run.errors
    assert len({i.country for i in CollectedItem.query.all()}) >= 3


def test_reddit_skipped_without_keys(app):
    app.config.update(REDDIT_CLIENT_ID="", REDDIT_CLIENT_SECRET="", COLLECT_MAX_PER_RUN=100)
    session = FakeSession()
    run = collector.run_collection(session)
    assert run.errors == "" and run.added > 0
    assert not any("reddit.com" in u for u in session.calls)


def test_reddit_uses_oauth_with_keys(app):
    session = FakeSession()
    collector.run_collection(session)
    assert any(u.startswith("https://oauth.reddit.com/") for u in session.calls)
    assert session.headers["Authorization"] == "bearer tok"


def test_cli_collect(app, monkeypatch):
    monkeypatch.setattr(collector, "_new_session", lambda cfg: FakeSession())
    result = app.test_cli_runner().invoke(args=["collect"])
    assert "추가" in result.output and result.exit_code == 0


# ------------------------------------------------------------------ 번역
ARTICLE_HTML = """<html><head><title>Samsung</title>
<meta property="og:image" content="/img/lead.jpg"></head><body><article>
<h1>Samsung shares jump on chip demand</h1>
<p>Samsung Electronics shares rose sharply on Monday after the company reported strong demand for memory chips
used in artificial intelligence servers, according to analysts in Seoul.</p>
<p>The rally lifted the KOSPI index to a record high, and foreign investors were net buyers for a fifth day.</p>
<p>Analysts said the outlook for the second half remains positive despite tariff concerns in the United States.</p>
</article></body></html>""".encode()


class FakeStream:
    def __init__(self, message, calls, kwargs):
        self.message, self.calls, self.kwargs = message, calls, kwargs

    def __enter__(self):
        self.calls.append(self.kwargs)
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.message


def fake_client(parsed, stop_reason="end_turn"):
    calls = []
    message = SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed)
    messages = SimpleNamespace(stream=lambda **kw: FakeStream(message, calls, kw))
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), calls


def make_item(**kw):
    defaults = dict(source_type="gnews", url="https://news.google.com/rss/articles/CBMiXYZ", title="Samsung shares jump",
                    source_name="Example Wire", country="us", lang="en", category_hint="economy",
                    comments=[{"author": "a", "body": "Great news", "score": 5},
                              {"author": "b", "body": "Buy the dip", "score": 3}])
    defaults.update(kw)
    item = CollectedItem(**defaults)
    db.session.add(item)
    db.session.commit()
    return item


@pytest.fixture
def article_fetch(monkeypatch):
    import googlenewsdecoder

    monkeypatch.setattr(googlenewsdecoder, "gnewsdecoder",
                        lambda url, timeout=None: {"success": True, "decoded_url": "https://wire.example/samsung"})
    fetched = []

    def fake_fetch(url, ua):
        fetched.append(url)
        return url, ARTICLE_HTML

    monkeypatch.setattr(tr, "fetch_html", fake_fetch)
    return fetched


def test_translate_summarizes_article_and_all_comments(app, monkeypatch, article_fetch):
    parsed = tr.Translation(
        title_ko="삼성 주가, 반도체 수요에 급등", summary_ko="가" * 700, category="economy",
        comments_ko=[tr.CommentKo(index=1, text="저점 매수 각"), tr.CommentKo(index=0, text="좋은 소식")],
    )
    client, calls = fake_client(parsed)
    monkeypatch.setattr(tr, "_get_client", lambda: client)
    item = make_item()

    assert tr.start_translation(item)  # TestConfig: 동기 실행
    item = db.session.get(CollectedItem, item.id)
    assert item.translate_status == "done", item.translate_error
    assert article_fetch == ["https://wire.example/samsung"]
    assert item.resolved_url == "https://wire.example/samsung"
    assert item.image_url == "https://wire.example/img/lead.jpg"  # og:image 절대 주소
    assert len(item.summary_ko) <= 500
    assert item.comments_ko == ["좋은 소식", "저점 매수 각"]  # index 로 순서 맞춤
    # Claude 에는 추출한 본문과 번호 매긴 댓글이 모두 전달됨
    prompt = calls[0]["messages"][0]["content"]
    assert "KOSPI index to a record high" in prompt and "[0] Great news" in prompt and "[1] Buy the dip" in prompt
    assert calls[0]["model"] == "claude-opus-5-5" and calls[0]["fallbacks"] == "default"
    assert "500자 이내" in calls[0]["system"]


def test_translate_reddit_self_post_without_article(app, monkeypatch, article_fetch):
    parsed = tr.Translation(title_ko="서울 지하철", summary_ko="요약", category="fun",
                            comments_ko=[tr.CommentKo(index=0, text="동의")])
    client, calls = fake_client(parsed)
    monkeypatch.setattr(tr, "_get_client", lambda: client)
    item = make_item(source_type="reddit", url="https://www.reddit.com/r/korea/comments/x/y/", country="reddit",
                     snippet="Just visited Seoul.", image_url="https://i.redd.it/p.jpg",
                     comments=[{"author": "a", "body": "agree", "score": 1}])
    tr.start_translation(item)
    item = db.session.get(CollectedItem, item.id)
    assert item.translate_status == "done" and article_fetch == []
    assert item.image_url == "https://i.redd.it/p.jpg" and item.comments_ko == ["동의"]
    assert "Just visited Seoul." in calls[0]["messages"][0]["content"]


def test_translate_falls_back_when_article_unavailable(app, monkeypatch):
    def broken(url, ua):
        raise tr.TranslationError("403 Forbidden")

    import googlenewsdecoder

    monkeypatch.setattr(googlenewsdecoder, "gnewsdecoder",
                        lambda url, timeout=None: {"success": True, "decoded_url": "https://paywall.example/a"})
    monkeypatch.setattr(tr, "fetch_html", broken)
    parsed = tr.Translation(title_ko="t", summary_ko="s", category="politics", comments_ko=[])
    client, _ = fake_client(parsed)
    monkeypatch.setattr(tr, "_get_client", lambda: client)
    item = make_item(comments=[], snippet="short snippet")
    tr.start_translation(item)
    item = db.session.get(CollectedItem, item.id)
    assert item.translate_status == "done"
    assert "원문 본문을 가져오지 못했습니다" in item.translate_note


def test_translate_error_is_shown(app, monkeypatch, article_fetch):
    client, _ = fake_client(None, stop_reason="refusal")
    monkeypatch.setattr(tr, "_get_client", lambda: client)
    item = make_item()
    tr.start_translation(item)
    item = db.session.get(CollectedItem, item.id)
    assert item.translate_status == "error" and "거절" in item.translate_error


def test_desk_translate_button_flow(app, client, monkeypatch, article_fetch):
    from app.models import User

    op = User(username="op", email="op@example.com", role="operator")
    op.set_password("password123")
    db.session.add(op)
    db.session.commit()
    parsed = tr.Translation(title_ko="삼성 주가 급등", summary_ko="요약문", category="economy",
                            comments_ko=[tr.CommentKo(index=0, text="좋은 소식"), tr.CommentKo(index=1, text="매수")])
    fake, _ = fake_client(parsed)
    monkeypatch.setattr(tr, "_get_client", lambda: fake)
    item = make_item()
    client.post("/login", data={"email": "op@example.com", "password": "password123"})

    html = client.get(f"/desk/{item.id}").get_data(as_text=True)
    assert html.count('action="/desk/%d/translate"' % item.id) == 2  # 상단·하단 번역 버튼
    client.post(f"/desk/{item.id}/translate")
    html = client.get(f"/desk/{item.id}").get_data(as_text=True)
    assert "삼성 주가 급등" in html and "요약문" in html and "좋은 소식" in html and "게시글로 작성" in html
    assert client.get(f"/desk/{item.id}/status.json").get_json() == {"translate_status": "done"}


def test_private_urls_blocked():
    assert not tr.is_public_http_url("http://127.0.0.1/admin")
    assert not tr.is_public_http_url("http://localhost:8000/")
    assert not tr.is_public_http_url("http://169.254.169.254/latest/meta-data")
    assert not tr.is_public_http_url("file:///etc/passwd")
    assert not tr.is_public_http_url("http://10.0.0.5/")


def test_trim_keeps_sentence_boundary():
    text = "첫 문장입니다. " * 80
    out = tr._trim(text, 500)
    assert len(out) <= 500 and out.endswith("다.")
