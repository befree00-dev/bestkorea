import json
from types import SimpleNamespace

import pytest

from app.collector import translate as tr
from app.collector.browser_import import ImportError_, detect, parse
from app.collector.classify import classify
from app.extensions import db
from app.models import CollectedItem


@pytest.mark.parametrize("text,cat", [
    ("Samsung shares jump on strong exports", "economy"),
    ("SK Hynix HBM chip demand soars", "it"),
    ("Korean birth rate hits record low", "society"),
    ("Son Heung-min scores twice for Tottenham", "sports"),
    ("BLACKPINK announce world tour", "entertainment"),
    ("T1 Faker wins Worlds again", "game"),
    ("韓国の大統領が来日", "politics"),
    ("Something with no keywords", "fun"),
])
def test_classify(text, cat):
    assert classify(text) == cat


# ------------------------------------------------------------------ 번역
FULL_BODY_KO = "삼성전자 주가가 월요일 급등했다.\n\n" + "코스피 지수는 사상 최고치를 기록했다. " * 120 + "\n\n하반기 전망도 긍정적이다."

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
                    source_name="Example Wire", country="na", lang="en", category_hint="economy",
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


def test_translate_full_article_and_all_comments(app, monkeypatch, article_fetch):
    parsed = tr.Translation(
        title_ko="삼성 주가, 반도체 수요에 급등", body_ko=FULL_BODY_KO, category="economy", region="unknown",
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
    assert item.summary_ko == FULL_BODY_KO.strip()  # 줄이지 않고 본문 전체 번역을 그대로 저장
    assert "저작권" in item.translate_note  # 언론사 기사 전문 번역 경고
    assert item.comments_ko == ["좋은 소식", "저점 매수 각"]  # index 로 순서 맞춤
    # Claude 에는 추출한 본문과 번호 매긴 댓글이 모두 전달됨
    prompt = calls[0]["messages"][0]["content"]
    assert "KOSPI index to a record high" in prompt and "[0] Great news" in prompt and "[1] Buy the dip" in prompt
    assert calls[0]["model"] == "claude-opus-5-5" and calls[0]["fallbacks"] == "default"
    assert "본문 전체" in calls[0]["system"] and "요약하거나 줄이지" in calls[0]["system"]
    assert calls[0]["max_tokens"] == 128000


def test_translate_youtube_uses_description(app, monkeypatch, article_fetch):
    parsed = tr.Translation(title_ko="외국인 길거리 음식 체험", body_ko="번역문", category="fun", region="unknown",
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
    assert "영상 설명을 번역" in item.translate_note


def test_translate_reddit_self_post_without_article(app, monkeypatch, article_fetch):
    parsed = tr.Translation(title_ko="서울 지하철", body_ko="번역문", category="fun", region="unknown",
                            comments_ko=[tr.CommentKo(index=0, text="동의")])
    client, calls = fake_client(parsed)
    monkeypatch.setattr(tr, "_get_client", lambda: client)
    item = make_item(source_type="reddit", url="https://www.reddit.com/r/korea/comments/x/y/", country=None,
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
    parsed = tr.Translation(title_ko="t", body_ko="s", category="politics", region="unknown", comments_ko=[])
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
    parsed = tr.Translation(title_ko="삼성 주가 급등", body_ko="번역된 본문", category="economy", region="unknown",
                            comments_ko=[tr.CommentKo(index=0, text="좋은 소식"), tr.CommentKo(index=1, text="매수")])
    fake, _ = fake_client(parsed)
    monkeypatch.setattr(tr, "_get_client", lambda: fake)
    item = make_item()
    client.post("/login", data={"email": "op@example.com", "password": "password123"})

    html = client.get(f"/desk/{item.id}").get_data(as_text=True)
    assert html.count('action="/desk/%d/translate"' % item.id) == 2  # 상단·하단 번역 버튼
    client.post(f"/desk/{item.id}/translate")
    html = client.get(f"/desk/{item.id}").get_data(as_text=True)
    assert "삼성 주가 급등" in html and "번역된 본문" in html and "좋은 소식" in html and "게시판에 올리기" in html
    assert client.get(f"/desk/{item.id}/status.json").get_json() == {"translate_status": "done"}


def test_private_urls_blocked():
    assert not tr.is_public_http_url("http://127.0.0.1/admin")
    assert not tr.is_public_http_url("http://localhost:8000/")
    assert not tr.is_public_http_url("http://169.254.169.254/latest/meta-data")
    assert not tr.is_public_http_url("file:///etc/passwd")
    assert not tr.is_public_http_url("http://10.0.0.5/")


def test_clean_text_keeps_paragraphs():
    from app.collector.fetchers import clean_text

    raw = "First paragraph  line.\n\n\n\nSecond   paragraph.\nNext line"
    assert clean_text(raw, keep_lines=True) == "First paragraph line.\n\nSecond paragraph.\nNext line"
    assert clean_text(raw) == "First paragraph line. Second paragraph. Next line"


# ------------------------------------------------------------------ 브라우저에서 가져오기
def reddit_json(num_comments=42, over_18=False, permalink="/r/korea/comments/abc123/seoul_subway/", is_self=True,
                url=None):
    post = dict(id="abc123", title="Seoul subway is amazing", subreddit="korea", permalink=permalink,
                num_comments=num_comments, over_18=over_18, is_self=is_self,
                selftext="Just visited &amp; loved it.\n\nSecond paragraph", created_utc=1764100000,
                url=url or "https://www.reddit.com" + permalink,
                preview={"images": [{"source": {"url": "https://preview.redd.it/x.jpg?a=1&amp;b=2"}}]})
    comments = [
        {"kind": "t1", "data": {"author": "AutoModerator", "body": "rules", "score": 1, "stickied": True}},
        {"kind": "t1", "data": {"author": "bob", "body": "Clean and fast", "score": 50}},
        {"kind": "t1", "data": {"author": "alice", "body": "Best transit in the world", "score": 120}},
        {"kind": "t1", "data": {"author": "x", "body": "[removed]", "score": 999}},
        {"kind": "more", "data": {}},
    ]
    return json.dumps([{"data": {"children": [{"kind": "t3", "data": post}]}},
                       {"data": {"children": comments}}])


def youtube_payload(**kw):
    d = dict(id="dQw4w9WgXcQ", title="Foreigners try Korean street food", text="We tried 10 foods.\n\nMyeongdong!",
             author="Example Reacts", published="2026-11-25", num_comments=1234,
             comments=[{"author": "@a", "body": "looks tasty", "score": 5}, {"author": "@b", "body": "I want to go", "score": 99}])
    d.update(kw)
    return json.dumps(d)


def x_payload(**kw):
    d = dict(id="1861000000000000001", handle="traveler", name="Trip Lover", text="Seoul is so clean\nLoved it",
             lang="en", image="https://pbs.twimg.com/media/a.jpg", published="2026-11-25T03:00:00.000Z",
             num_comments=340, comments=[{"author": "@fan8", "body": "@traveler @friend Best trip", "score": 40},
                                         {"author": "@fan9", "body": "Agree", "score": 3}])
    d.update(kw)
    return json.dumps(d)


def test_parse_reddit():
    item, external = parse("reddit", reddit_json(), 10, 50)
    assert item.url == "https://www.reddit.com/r/korea/comments/abc123/seoul_subway/"
    assert item.source_name == "r/korea" and item.num_comments == 42 and external is None
    assert [c["author"] for c in item.reactions] == ["alice", "bob"]  # 점수순, 자동모더레이터·삭제 제외
    assert item.summary == "Just visited & loved it.\n\nSecond paragraph"  # 문단 유지
    assert item.image_url == "https://preview.redd.it/x.jpg?a=1&b=2"


def test_parse_reddit_link_post():
    _, external = parse("reddit", reddit_json(is_self=False, url="https://news.example/korea"), 10, 50)
    assert external == "https://news.example/korea"


def test_parse_youtube():
    item, _ = parse("youtube", youtube_payload(), 10, 50)
    assert item.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ" and item.country is None  # 지역은 번역·운영자가 결정
    assert item.image_url == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    assert item.num_comments == 1234 and [c["author"] for c in item.reactions] == ["@b", "@a"]
    assert item.summary == "We tried 10 foods.\n\nMyeongdong!" and item.source_name == "Example Reacts"


def test_parse_x_builds_url_and_filters_image():
    item, _ = parse("x", x_payload(), 10, 50)
    assert item.url == "https://x.com/traveler/status/1861000000000000001"
    assert item.source_name == "@traveler (Trip Lover)" and item.lang == "en" and item.num_comments == 340
    assert item.country is None  # 영어는 여러 지역에서 쓰므로 추정하지 않음
    assert parse("x", x_payload(lang="ja"), 10, 50)[0].country == "jp"
    assert item.image_url == "https://pbs.twimg.com/media/a.jpg"
    assert item.reactions[0]["body"] == "Best trip"  # 답글 앞 @멘션 제거
    item, _ = parse("x", x_payload(image="https://evil.example/a.jpg"), 10, 50)
    assert item.image_url is None  # 허용된 이미지 서버만


def test_comment_limit_applies():
    item, _ = parse("youtube", youtube_payload(comments=[{"author": str(i), "body": f"c{i}", "score": i}
                                                        for i in range(80)]), 10, 50)
    assert len(item.reactions) == 50 and item.reactions[0]["score"] == 79


@pytest.mark.parametrize("site,payload,message", [
    ("reddit", reddit_json(num_comments=5), "수집 기준"),
    ("reddit", reddit_json(over_18=True), "NSFW"),
    ("reddit", reddit_json(permalink="https://evil.example/"), "주소"),
    ("reddit", '{"not": "reddit"}', "형식"),
    ("reddit", "", "비어"),
    ("youtube", youtube_payload(num_comments=3, comments=[{"author": "a", "body": "b", "score": 1}]), "수집 기준"),
    ("youtube", youtube_payload(id="../../etc"), "영상 ID"),
    ("youtube", youtube_payload(comments=[]), "댓글을 하나도"),
    ("x", x_payload(handle="evil.com/x"), "주소"),
    ("x", x_payload(text=""), "본문"),
    ("x", "[1,2]", "형식"),
])
def test_parse_rejects(site, payload, message):
    with pytest.raises(ImportError_, match=message):
        parse(site, payload, 10, 50)


def test_detect_pasted_content():
    assert detect(json.dumps({"site": "x", "json": x_payload()}))[0] == "x"
    assert detect(reddit_json())[0] == "reddit"
    with pytest.raises(ImportError_):
        detect('{"hello": 1}')


def _staff_client(client, role="operator"):
    from app.models import User

    u = User(username=role, email=f"{role}@example.com", role=role)
    u.set_password("password123")
    db.session.add(u)
    db.session.commit()
    client.post("/login", data={"email": f"{role}@example.com", "password": "password123"})
    return client


def test_import_page_and_bookmarklet(app, client):
    _staff_client(client)
    html = client.get("/desk/import").get_data(as_text=True)
    assert 'href="javascript:' in html and "BestKorea로 가져오기" in html
    assert client.get("/desk/import/reddit").status_code == 200  # 예전 버튼 주소 호환


@pytest.mark.parametrize("site,payload", [
    ("reddit", reddit_json()), ("youtube", youtube_payload()), ("x", x_payload()),
])
def test_import_each_site(app, client, site, payload):
    _staff_client(client)
    r = client.post("/desk/import", data={"site": site, "payload": payload})
    item = CollectedItem.query.one()
    assert r.headers["Location"].endswith(f"/desk/{item.id}")
    assert item.source_type == site and item.status == "new" and len(item.comments) == 2
    # 같은 글을 다시 가져오면 기존 글로 이동
    r = client.post("/desk/import", data={"site": site, "payload": payload})
    assert CollectedItem.query.count() == 1 and r.headers["Location"].endswith(f"/desk/{item.id}")


def test_import_pasted_without_site(app, client):
    _staff_client(client)
    client.post("/desk/import", data={"payload": json.dumps({"site": "youtube", "json": youtube_payload()})})
    assert CollectedItem.query.one().source_type == "youtube"


def test_import_rejected_payload_is_not_saved(app, client):
    _staff_client(client)
    r = client.post("/desk/import", data={"site": "x", "payload": x_payload(num_comments=2, comments=[])},
                    follow_redirects=True)
    assert CollectedItem.query.count() == 0 and "수집 기준" in r.get_data(as_text=True)


def test_import_staff_only(app, client):
    _staff_client(client, role="reporter")
    assert client.get("/desk/import").status_code == 403
    assert client.post("/desk/import", data={"site": "reddit", "payload": reddit_json()}).status_code == 403


def test_bookmarklet_script_is_valid_js(app, client, tmp_path):
    """북마클릿 코드를 한 줄로 만든 결과가 문법적으로 올바른지 node 로 확인."""
    import shutil
    import subprocess
    from urllib.parse import unquote

    node = shutil.which("node")
    if not node:
        pytest.skip("node 없음")
    _staff_client(client)
    html = client.get("/desk/import").get_data(as_text=True)
    href = html.split('href="javascript:', 1)[1].split('"', 1)[0]
    js = tmp_path / "b.js"
    js.write_text(unquote(href.replace("&amp;", "&")))
    out = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


def test_translation_sets_region_only_when_unknown(app, monkeypatch, article_fetch):
    parsed = tr.Translation(title_ko="t", body_ko="b", category="it", region="sea", comments_ko=[])
    client, _ = fake_client(parsed)
    monkeypatch.setattr(tr, "_get_client", lambda: client)
    unknown = make_item(comments=[], url="https://example.com/a1", source_type="youtube", country=None, snippet="x")
    known = make_item(comments=[], url="https://example.com/a2", source_type="youtube", country="jp", snippet="x")
    tr.start_translation(unknown)
    tr.start_translation(known)
    assert db.session.get(CollectedItem, unknown.id).country == "sea"
    assert db.session.get(CollectedItem, known.id).country == "jp"
    assert db.session.get(CollectedItem, unknown.id).category_ko == "it"


def test_import_reports_read_count_and_stop_reason(app, client):
    _staff_client(client)
    payload = json.loads(x_payload())
    payload["debug"] = {"v": 3, "stop": "section", "clicked": 2, "read": 2, "articles": 9, "no_text": 0,
                        "notes": ["Show probable spam", "Discover more"], "logged_in": True}
    r = client.post("/desk/import", data={"site": "x", "payload": json.dumps(payload)}, follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "전체 340개 중 2개 저장" in html and "다른 섹션이 시작됨" in html and "답글 더 보기&#39; 2번" in html
    assert "버튼 v3" in html and "화면에서 본 답글 9개" in html and "Show probable spam | Discover more" in html
    assert "로그인이 안 된" not in html


def test_import_flags_old_button_and_logged_out(app, client):
    _staff_client(client)
    r = client.post("/desk/import", data={"site": "x", "payload": x_payload()}, follow_redirects=True)
    assert "예전 가져오기 버튼" in r.get_data(as_text=True)
    payload = json.loads(x_payload(id="1861000000000000999"))
    payload["debug"] = {"v": 3, "stop": "idle", "articles": 9, "logged_in": False}
    r = client.post("/desk/import", data={"site": "x", "payload": json.dumps(payload)}, follow_redirects=True)
    assert "X 로그인이 안 된 것 같습니다" in r.get_data(as_text=True)


def test_import_reports_hidden_tab(app, client):
    _staff_client(client)
    payload = json.loads(x_payload())
    payload["debug"] = {"v": 4, "stop": "idle", "articles": 11, "hidden": True, "logged_in": True}
    r = client.post("/desk/import", data={"site": "x", "payload": json.dumps(payload)}, follow_redirects=True)
    assert "읽는 도중 탭이 가려졌습니다" in r.get_data(as_text=True)
