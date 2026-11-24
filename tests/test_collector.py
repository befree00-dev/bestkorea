import json
from types import SimpleNamespace

import pytest

from app import collector
from app.collector.classify import classify
from app.collector.fetchers import RedditClient, fetch_reddit, fetch_rss
from app.models import CollectLog, Post, Reaction

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
             subreddit="korea", score=500, is_self=True, selftext="Just visited.", created_utc=1764000000),
        dict(id=f"{prefix}2", title="low score", permalink=f"/r/korea/comments/{prefix}2/x/", subreddit="korea",
             score=1, is_self=True, created_utc=1764000000),
        dict(id=f"{prefix}3", title="nsfw", permalink=f"/r/korea/comments/{prefix}3/x/", subreddit="korea",
             score=900, over_18=True, created_utc=1764000000),
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
        prefix = str(abs(hash(url)) % 10000)
        return FakeResponse(data=reddit_listing(prefix))

    def post(self, *a, **k):
        raise AssertionError("no oauth expected")


def test_fetch_rss_strips_publisher_suffix():
    items = fetch_rss(dict(id="t", url="https://news.google.com/rss", country="us", lang="en"), FakeSession(), 5)
    assert [i.title for i in items][:2] == ["Samsung shares jump on chip demand", "Son Heung-min scores twice"]
    assert items[0].source_name == "Example Wire"
    assert items[0].summary == ""  # 제목 반복 요약 제거
    assert items[0].published_at is not None


def test_fetch_reddit_filters_and_reactions():
    client = RedditClient(FakeSession())
    items = fetch_reddit(dict(id="r", sub="korea", mode="top", category=None), client, 5)
    assert len(items) == 1  # 저점수/NSFW 제외
    it = items[0]
    assert it.url.startswith("https://www.reddit.com/r/korea/comments/")
    assert [r["author"] for r in it.reactions] == ["alice", "carol"]


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


def test_run_collection_saves_dedups_and_logs(app):
    app.config.update(COLLECT_MAX_PER_RUN=100)
    run = collector.run_collection(FakeSession())
    assert run.added > 10  # 하루 10건 이상 목표
    assert run.errors == ""
    n = Post.query.count()
    assert {p.board for p in Post.query.filter(Post.source_url.like("%/a1"))} <= {"economy", "entertainment", "game", "sports"}
    assert Post.query.filter(Post.source_url.like("%/a1"), Post.country == "jp").first().board == "economy"
    assert Post.query.filter(Post.country == "reddit").count() > 0
    assert Reaction.query.count() > 0
    # 같은 데이터로 다시 실행하면 중복 저장 없음
    run2 = collector.run_collection(FakeSession())
    assert run2.added == 0 and Post.query.count() == n
    assert CollectLog.query.count() == 2


def test_run_collection_respects_cap_and_records_errors(app):
    app.config.update(COLLECT_MAX_PER_RUN=5)
    run = collector.run_collection(FakeSession(fail=("reddit.com/r/kpop",)))
    assert run.added == 5
    assert "rd-kpop" in run.errors


def test_interleave_mixes_countries(app):
    app.config.update(COLLECT_MAX_PER_RUN=6)
    collector.run_collection(FakeSession())
    countries = {p.country for p in Post.query.all()}
    assert len(countries) >= 3


def test_translation_used_when_enabled(app, monkeypatch):
    from app.collector import enrich as enrich_mod

    app.config.update(TRANSLATE_ENABLED=True, COLLECT_MAX_PER_RUN=100)

    def fake_enrich(item, model):
        return SimpleNamespace(title_ko="번역: " + item.title, summary_ko="요약", category="fun",
                               reactions_ko=[f"반응{i}" for i in range(len(item.reactions))])

    monkeypatch.setattr(enrich_mod, "enrich", fake_enrich)
    collector.run_collection(FakeSession())
    p = Post.query.filter(Post.source_url.like("%/a3"), Post.country == "eu").first()
    assert p.title.startswith("번역: ") and p.original_title == "韓国の大統領が来日"
    assert p.board == "fun"  # 소스에 카테고리 지정이 없으면 Claude 분류 사용
    r = Reaction.query.filter_by(author="alice").first()
    assert r.body_ko == "반응0"


def test_enrich_handles_refusal(monkeypatch):
    from app.collector import enrich as enrich_mod
    from app.collector.fetchers import Item

    class FakeMessages:
        def parse(self, **kw):
            assert kw["model"] == "claude-opus-5-5"
            assert kw["fallbacks"] == "default"
            return SimpleNamespace(stop_reason="refusal", parsed_output=None)

    monkeypatch.setattr(enrich_mod, "_get_client", lambda: SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages())))
    item = Item(source_id="x", title="t", url="u", country="us", lang="en")
    assert enrich_mod.enrich(item, "claude-opus-5-5") is None


def test_cli_collect(app, monkeypatch):
    monkeypatch.setattr(collector, "_new_session", lambda cfg: FakeSession())
    result = app.test_cli_runner().invoke(args=["collect"])
    assert "추가" in result.output and result.exit_code == 0
