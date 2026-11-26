from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import collector
from app.collector import translate as tr
from app.collector import youtube
from app.collector.classify import classify
from app.collector.fetchers import mostly_korean
from app.extensions import db
from app.models import CollectedItem, CollectLog, Post

# videoId -> (댓글 수 또는 None=댓글 사용 중지, 제목, 오디오 언어)
VIDEOS = {
    "vid_en_0001": (5400, "Foreigners try Korean street food", "en"),
    "vid_en_0002": (3100, "Why K-pop dominates the charts", "en"),
    "vid_en_0003": (900, "Seoul subway tour", "en-US"),
    "vid_en_0004": (9, "Only nine comments about Korea", "en"),  # 기준 미달
    "vid_en_0005": (None, "Comments disabled Korea video", "en"),  # 댓글 사용 중지
    "vid_ko_0006": (8000, "한국 예능 하이라이트 모음", "ko"),  # 한국어 영상 제외
    "vid_ja_0007": (2500, "韓国旅行Vlog ソウル", "ja"),
    "vid_ja_0008": (1500, "韓国の物価が高すぎる", "ja"),
    "vid_zh_0009": (700, "韩国综艺反应", "zh-Hans"),
    "vid_hg_0010": (6000, "Korea 한국 여행 브이로그 서울 맛집", ""),  # 제목 대부분 한글 → 제외
    "vid_es_0011": (400, "Reacción a Corea del Sur", "es"),
    "vid_pt_0012": (300, "Reagindo à Coreia do Sul", "pt"),
}
SEARCH = {
    "en": ["vid_en_0001", "vid_en_0002", "vid_en_0003", "vid_en_0004", "vid_en_0005", "vid_ko_0006", "vid_hg_0010"],
    "ja": ["vid_ja_0007", "vid_ja_0008", "vid_en_0001"],  # 중복은 한 번만
    "zh-Hans": ["vid_zh_0009"], "es": ["vid_es_0011"], "pt": ["vid_pt_0012"], "de": [], "fr": [],
}


class FakeResponse:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.text = data, status, str(data)

    def json(self):
        return self._data


class FakeYouTube:
    def __init__(self, videos=None, quota=False):
        self.videos = dict(VIDEOS if videos is None else videos)
        self.quota = quota
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        path = url.rsplit("/", 1)[1]
        self.calls.append((path, dict(params or {})))
        assert params["key"] == "test-key"
        if self.quota:
            return FakeResponse({"error": {"code": 403, "message": "quota", "errors": [{"reason": "quotaExceeded"}]}}, 403)
        if path == "search":
            ids = [v for v in SEARCH.get(params["relevanceLanguage"], []) if v in self.videos]
            return FakeResponse({"items": [{"id": {"videoId": v}} for v in ids]})
        if path == "videos":
            items = []
            for vid in params["id"].split(","):
                count, title, lang = self.videos[vid]
                stats = {} if count is None else {"commentCount": str(count)}
                items.append({"id": vid, "statistics": stats, "snippet": {
                    "title": title, "description": f"Description of {title}", "channelTitle": "Channel " + vid,
                    "publishedAt": "2026-11-24T03:00:00Z", "defaultAudioLanguage": lang,
                    "thumbnails": {"high": {"url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"}}}})
            return FakeResponse({"items": items})
        if path == "commentThreads":
            return FakeResponse({"items": [
                {"snippet": {"topLevelComment": {"snippet": {"authorDisplayName": f"@user{i}",
                                                             "textDisplay": f"comment {i} on {params['videoId']}",
                                                             "likeCount": 100 - i}}}}
                for i in range(3)]})
        raise AssertionError(path)


@pytest.fixture(autouse=True)
def youtube_key(app):
    app.config.update(YOUTUBE_API_KEY="test-key", PER_SITE_DAILY=10, MIN_COMMENTS=10)


# ------------------------------------------------------------------ YouTube 수집
def test_search_candidates_filters_and_sorts(app):
    errors = []
    items = youtube.search_candidates(app.config, FakeYouTube(), errors)
    assert errors == []
    assert [i.external_id for i in items] == [
        "vid_en_0001", "vid_en_0002", "vid_ja_0007", "vid_ja_0008", "vid_en_0003", "vid_zh_0009",
        "vid_es_0011", "vid_pt_0012",
    ]  # 댓글 9개·댓글 중지·한국어 영상 제외, 댓글 많은 순
    first = items[0]
    assert first.url == "https://www.youtube.com/watch?v=vid_en_0001" and first.num_comments == 5400
    assert first.image_url.endswith("/hqdefault.jpg") and first.source_name == "Channel vid_en_0001"
    assert first.published_at == datetime(2026, 11, 24, 3, 0)


def test_search_uses_last_24_hours_and_all_languages(app):
    fake = FakeYouTube()
    youtube.search_candidates(app.config, fake, [])
    searches = [p for path, p in fake.calls if path == "search"]
    assert {p["relevanceLanguage"] for p in searches} == {"en", "ja", "zh-Hans", "es", "pt", "de", "fr"}
    since = datetime.fromisoformat(searches[0]["publishedAfter"].replace("Z", "+00:00"))
    assert 23.9 < (datetime.now(timezone.utc) - since).total_seconds() / 3600 < 24.1


def test_collect_keeps_top_n_per_site_with_comments(app):
    app.config.update(PER_SITE_DAILY=3)
    fake = FakeYouTube()
    run = collector.run_collection(fake)
    assert run.added == 3 and run.errors == ""
    assert Post.query.count() == 0  # 사이트에는 자동 게시하지 않음
    rows = CollectedItem.query.order_by(CollectedItem.num_comments.desc()).all()
    assert [r.source_id for r in rows] == ["vid_en_0001", "vid_en_0002", "vid_ja_0007"]
    assert rows[0].source_type == "youtube" and rows[0].country == "youtube"
    assert [c["author"] for c in rows[0].comments] == ["@user0", "@user1", "@user2"]
    # 댓글은 수집함에 넣는 영상만 가져온다 (할당량 절약)
    assert sorted(p["videoId"] for path, p in fake.calls if path == "commentThreads") == [
        "vid_en_0001", "vid_en_0002", "vid_ja_0007"]


def test_rerun_replaces_untouched_but_keeps_worked_items(app):
    app.config.update(PER_SITE_DAILY=3)
    collector.run_collection(FakeYouTube())
    worked = CollectedItem.query.filter_by(source_id="vid_ja_0007").one()
    worked.translate_status = "done"  # 운영자가 번역한 글
    db.session.commit()

    videos = dict(VIDEOS)
    videos["vid_pt_0012"] = (9999, "Reagindo à Coreia do Sul", "pt")  # 새로 급상승
    videos["vid_en_0002"] = (3300, "Why K-pop dominates the charts", "en")
    run = collector.run_collection(FakeYouTube(videos))
    ids = {r.source_id for r in CollectedItem.query.all()}
    # 1위 신규 영상 추가, 손대지 않은 하위 글(vid_en_0002)은 교체, 번역한 글은 유지
    assert ids == {"vid_pt_0012", "vid_en_0001", "vid_ja_0007"}
    assert run.added == 1 and run.skipped == 1


def test_comment_counts_refresh_for_existing(app):
    collector.run_collection(FakeYouTube())
    videos = dict(VIDEOS)
    videos["vid_en_0003"] = (4321, "Seoul subway tour", "en-US")
    assert collector.run_collection(FakeYouTube(videos)).added == 0
    assert CollectedItem.query.filter_by(source_id="vid_en_0003").one().num_comments == 4321


def test_no_api_key_means_nothing_collected(app):
    app.config.update(YOUTUBE_API_KEY="")
    fake = FakeYouTube()
    run = collector.run_collection(fake)
    assert run.added == 0 and fake.calls == []
    assert "YOUTUBE_API_KEY" in run.errors


def test_quota_exceeded_is_reported_once(app):
    fake = FakeYouTube(quota=True)
    run = collector.run_collection(fake)
    assert run.added == 0 and "할당량" in run.errors
    assert len(fake.calls) == 1 and len(run.errors.splitlines()) == 1  # 첫 요청에서 멈춤


def test_kst_midnight():
    now = datetime(2026, 11, 24, 16, 30, tzinfo=timezone.utc)  # 한국 시간 11/25 01:30
    assert collector.kst_midnight_utc(now) == datetime(2026, 11, 24, 15, 0)


def test_mostly_korean():
    assert mostly_korean("한국 예능 하이라이트 모음") and not mostly_korean("Foreigners try Korean food")
    assert mostly_korean("Korea 한국 여행 브이로그 서울 맛집")


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


def test_cli_collect(app, monkeypatch):
    monkeypatch.setattr(collector, "_new_session", lambda cfg: FakeYouTube())
    result = app.test_cli_runner().invoke(args=["collect"])
    assert result.exit_code == 0 and "YouTube" in result.output


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


def test_translate_youtube_uses_description(app, monkeypatch, article_fetch):
    parsed = tr.Translation(title_ko="외국인 길거리 음식 체험", summary_ko="요약", category="fun",
                            comments_ko=[tr.CommentKo(index=0, text="맛있겠다")])
    client, calls = fake_client(parsed)
    monkeypatch.setattr(tr, "_get_client", lambda: client)
    item = make_item(source_type="youtube", url="https://www.youtube.com/watch?v=vid_en_0001", country="youtube",
                     snippet="We tried 10 street foods in Myeongdong.", image_url="https://i.ytimg.com/x.jpg",
                     comments=[{"author": "@a", "body": "looks tasty", "score": 9}])
    tr.start_translation(item)
    item = db.session.get(CollectedItem, item.id)
    assert item.translate_status == "done" and article_fetch == []  # 외부 페이지 요청 없음
    assert "Myeongdong" in calls[0]["messages"][0]["content"]
    assert "영상 제목과 설명" in item.translate_note


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


# ------------------------------------------------------------------ X(트위터) 수집
from app.collector import x as xsite  # noqa: E402
from app.models import SiteState  # noqa: E402

TWEETS = [  # (id, 답글 수, 언어, 본문)
    ("1001", 340, "en", "Seoul is the cleanest city I've ever visited"),
    ("1002", 120, "ja", "韓国のコンビニが便利すぎる"),
    ("1003", 9, "en", "Only nine replies about Korea"),
    ("1004", 900, "ko", "한국어 트윗은 제외"),
    ("1005", 55, "es", "Corea del Sur gana el partido"),
]


class FakeX:
    def __init__(self, status=200):
        self.calls, self.headers, self.status = [], {}, status

    def get(self, url, params=None, headers=None, timeout=None):
        assert headers["Authorization"] == "Bearer x-token"
        self.calls.append(dict(params))
        if self.status != 200:
            return FakeResponse({"title": "Too Many Requests", "detail": "Usage cap exceeded"}, self.status)
        q = params["query"]
        if q.startswith("conversation_id:"):
            cid = q.split()[0].split(":")[1]
            return FakeResponse({
                "data": [
                    {"id": f"{cid}r1", "text": "@origin @friend Totally agree", "author_id": "u9",
                     "public_metrics": {"like_count": 3}},
                    {"id": f"{cid}r2", "text": "@origin Best trip ever", "author_id": "u8",
                     "public_metrics": {"like_count": 40}},
                ],
                "includes": {"users": [{"id": "u9", "username": "fan9"}, {"id": "u8", "username": "fan8"}]},
            })
        return FakeResponse({
            "data": [{"id": i, "text": text, "lang": lang, "author_id": "u1", "created_at": "2026-11-26T01:00:00Z",
                      "public_metrics": {"reply_count": n, "like_count": 0},
                      "attachments": {"media_keys": ["m1"]} if i == "1001" else {}}
                     for i, n, lang, text in TWEETS],
            "includes": {"users": [{"id": "u1", "username": "traveler", "name": "Trip Lover"}],
                         "media": [{"media_key": "m1", "type": "photo", "url": "https://pbs.twimg.com/m1.jpg"}]},
        })


@pytest.fixture
def x_on(app):
    app.config.update(YOUTUBE_API_KEY="", X_BEARER_TOKEN="x-token", X_INTERVAL_HOURS=6,
                      X_SEARCH_MAX_RESULTS=50, X_REPLIES_PER_ITEM=20)


def test_x_search_filters_and_sorts(app, x_on):
    errors = []
    fake = FakeX()
    items = xsite.search_candidates(app.config, fake, errors)
    assert errors == []
    assert [i.external_id for i in items] == ["1001", "1002", "1005"]  # 답글 9개·한국어 제외, 답글 많은 순
    first = items[0]
    assert first.url == "https://x.com/traveler/status/1001" and first.num_comments == 340
    assert first.source_name == "@traveler (Trip Lover)" and first.image_url == "https://pbs.twimg.com/m1.jpg"
    params = fake.calls[0]
    assert params["max_results"] == 50 and "-is:retweet" in params["query"] and "-lang:ko" in params["query"]


def test_x_collect_with_replies_and_interval(app, x_on):
    fake = FakeX()
    run = collector.run_collection(fake)
    assert run.added == 3
    assert all(line.startswith("YouTube") for line in run.errors.splitlines())  # X 쪽 오류 없음
    row = CollectedItem.query.filter_by(source_id="1001").one()
    assert row.source_type == "x" and row.country == "x"
    # 답글: 앞의 @멘션 제거, 좋아요 많은 순
    assert [(c["author"], c["body"]) for c in row.comments] == [("@fan8", "Best trip ever"), ("@fan9", "Totally agree")]
    assert fake.calls[1]["max_results"] == 20
    # X_INTERVAL_HOURS 안에 다시 돌리면 X 는 요청하지 않음 (사용량 절약)
    fake2 = FakeX()
    collector.run_collection(fake2)
    assert fake2.calls == []
    assert db.session.get(SiteState, "x").last_run_at is not None


def test_x_usage_cap_is_reported(app, x_on):
    run = collector.run_collection(FakeX(status=429))
    assert run.added == 0 and "사용량 한도" in run.errors


def test_x_off_without_token_is_not_an_error(app):
    app.config.update(X_BEARER_TOKEN="")
    run = collector.run_collection(FakeYouTube())
    assert "X" not in run.errors


# ------------------------------------------------------------------ Reddit 가져오기 (북마클릿)
import json as _json  # noqa: E402


def reddit_json(num_comments=42, over_18=False, permalink="/r/korea/comments/abc123/seoul_subway/", is_self=True,
                url=None):
    post = dict(id="abc123", title="Seoul subway is amazing", subreddit="korea", permalink=permalink,
                num_comments=num_comments, over_18=over_18, is_self=is_self, selftext="Just visited &amp; loved it",
                created_utc=1764100000, url=url or "https://www.reddit.com" + permalink,
                preview={"images": [{"source": {"url": "https://preview.redd.it/x.jpg?a=1&amp;b=2"}}]})
    comments = [
        {"kind": "t1", "data": {"author": "AutoModerator", "body": "rules", "score": 1, "stickied": True}},
        {"kind": "t1", "data": {"author": "bob", "body": "Clean and fast", "score": 50}},
        {"kind": "t1", "data": {"author": "alice", "body": "Best transit in the world", "score": 120}},
        {"kind": "t1", "data": {"author": "x", "body": "[removed]", "score": 999}},
        {"kind": "more", "data": {}},
    ]
    return _json.dumps([{"data": {"children": [{"kind": "t3", "data": post}]}},
                        {"data": {"children": comments}}])


def test_parse_reddit_json():
    from app.collector.reddit_import import parse_reddit_json

    item, external = parse_reddit_json(reddit_json(), 10, 50)
    assert item.url == "https://www.reddit.com/r/korea/comments/abc123/seoul_subway/"
    assert item.source_name == "r/korea" and item.num_comments == 42 and external is None
    assert [c["author"] for c in item.reactions] == ["alice", "bob"]  # 점수순, 자동모더레이터·삭제 제외
    assert item.summary == "Just visited & loved it"
    assert item.image_url == "https://preview.redd.it/x.jpg?a=1&b=2"


def test_parse_reddit_json_link_post():
    from app.collector.reddit_import import parse_reddit_json

    _, external = parse_reddit_json(reddit_json(is_self=False, url="https://news.example/korea"), 10, 50)
    assert external == "https://news.example/korea"


@pytest.mark.parametrize("payload,message", [
    (reddit_json(num_comments=5), "수집 기준"),
    (reddit_json(over_18=True), "NSFW"),
    (reddit_json(permalink="https://evil.example/"), "주소"),
    ('{"not": "reddit"}', "형식"),
    ("", "비어"),
])
def test_parse_reddit_json_rejects(payload, message):
    from app.collector.reddit_import import RedditImportError, parse_reddit_json

    with pytest.raises(RedditImportError, match=message):
        parse_reddit_json(payload, 10, 50)


def _staff_client(app, client, role="operator"):
    from app.models import User

    u = User(username=role, email=f"{role}@example.com", role=role)
    u.set_password("password123")
    db.session.add(u)
    db.session.commit()
    client.post("/login", data={"email": f"{role}@example.com", "password": "password123"})
    return client


def test_import_reddit_route(app, client):
    _staff_client(app, client)
    html = client.get("/desk/import/reddit").get_data(as_text=True)
    assert 'href="javascript:' in html and "BestKorea로 가져오기" in html
    r = client.post("/desk/import/reddit", data={"payload": reddit_json()})
    item = CollectedItem.query.one()
    assert r.headers["Location"].endswith(f"/desk/{item.id}")
    assert item.source_type == "reddit" and item.status == "new" and len(item.comments) == 2
    # 같은 글을 다시 가져오면 기존 글로 이동
    r = client.post("/desk/import/reddit", data={"payload": reddit_json()})
    assert CollectedItem.query.count() == 1 and r.headers["Location"].endswith(f"/desk/{item.id}")
    # 기준 미달은 거절
    client.post("/desk/import/reddit", data={"payload": reddit_json(num_comments=3, permalink="/r/korea/comments/zz9/x/")})
    assert CollectedItem.query.count() == 1


def test_import_reddit_staff_only(app, client):
    _staff_client(app, client, role="reporter")
    assert client.get("/desk/import/reddit").status_code == 403
    assert client.post("/desk/import/reddit", data={"payload": reddit_json()}).status_code == 403
