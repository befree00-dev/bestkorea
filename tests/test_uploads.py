import io
import os

import pytest
from PIL import Image

from app.models import Post

from .test_site import make_post, make_user
from .conftest import login


def image_bytes(fmt="PNG", size=(40, 30), exif_gps=False):
    img = Image.new("RGB", size, (200, 30, 30))
    out = io.BytesIO()
    kwargs = {}
    if exif_gps:
        exif = Image.Exif()
        exif[0x8825] = {1: "N", 2: (37.0, 33.0, 0.0)}  # GPS 정보
        kwargs["exif"] = exif
    img.save(out, fmt, **kwargs)
    return out.getvalue()


@pytest.fixture
def uploads(app, tmp_path):
    app.config.update(UPLOAD_FOLDER=str(tmp_path / "uploads"))
    return tmp_path / "uploads"


def upload(client, data, name="a.png"):
    return client.post("/upload/image", data={"image": (io.BytesIO(data), name)}, content_type="multipart/form-data")


def test_upload_requires_login(client, uploads):
    r = upload(client, image_bytes())
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_upload_and_serve_image(client, uploads):
    make_user("m")
    login(client, "m@example.com")
    r = upload(client, image_bytes())
    url = r.get_json()["url"]
    assert r.status_code == 200 and url.startswith("/uploads/") and url.endswith(".png")
    served = client.get(url)
    assert served.status_code == 200 and served.mimetype == "image/png"
    assert served.headers["X-Content-Type-Options"] == "nosniff"


def test_upload_strips_exif_and_resizes(client, uploads):
    make_user("m")
    login(client, "m@example.com")
    url = upload(client, image_bytes("JPEG", size=(4000, 1000), exif_gps=True), "photo.jpg").get_json()["url"]
    saved = Image.open(os.path.join(uploads, url.rsplit("/", 1)[1]))
    assert saved.size == (2000, 500)  # 긴 변 2000px 로 줄임
    assert 0x8825 not in saved.getexif()  # 위치정보 제거


@pytest.mark.parametrize("data,name", [
    (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "x.svg"),
    (b"not an image at all", "x.png"),
    (b"GIF89a broken", "x.gif"),
])
def test_upload_rejects_non_images(client, uploads, data, name):
    make_user("m")
    login(client, "m@example.com")
    r = upload(client, data, name)
    assert r.status_code == 400 and "error" in r.get_json()
    assert not os.path.exists(uploads) or os.listdir(uploads) == []


def test_upload_size_limit(app, client, uploads):
    app.config.update(MAX_IMAGE_BYTES=1000)
    make_user("m")
    login(client, "m@example.com")
    r = upload(client, image_bytes(size=(400, 400)))
    assert r.status_code == 400 and "MB 이하" in r.get_json()["error"]


def test_body_images_render_safely(client, user):
    body = "\n".join([
        "첫 문단",
        "![서울 사진](/uploads/abc123.png)",
        "![외부](https://i.ytimg.com/vi/x/hqdefault.jpg)",
        "![나쁜](javascript:alert(1))",
        '![따옴표]("onerror=alert(1))',
        "문장 중간 ![이미지](/uploads/x.png) 은 그대로 글자",
        "<img src=x onerror=alert(1)>",
    ])
    p = make_post(board="community", body=body, user_id=user.id)
    html = client.get(f"/b/community/{p.id}").get_data(as_text=True)
    assert '<img src="/uploads/abc123.png" alt="서울 사진"' in html
    assert '<img src="https://i.ytimg.com/vi/x/hqdefault.jpg"' in html
    assert 'src="javascript:' not in html and "onerror=alert(1)>" not in html
    assert "![나쁜](javascript:alert(1))" in html  # 허용 안 되는 주소는 글자로 남음
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert 'content="첫 문단' in html  # 검색 설명에는 이미지 줄 제외


def test_preview_matches_post_rendering(client, user):
    login(client)
    r = client.post("/preview", data={"body": "안녕\n![](/uploads/a.png)\n끝"})
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and '<img src="/uploads/a.png"' in html and "안녕" in html and "끝" in html


def test_write_form_has_image_tools(client):
    make_user("r", "reporter")
    login(client, "r@example.com")
    html = client.get("/write").get_data(as_text=True)
    assert 'id="img-btn"' in html and 'id="preview-btn"' in html and "/upload/image" in html
    client.post("/write", data=dict(board="community", topic="chat", title="사진 글", body="사진\n![](/uploads/abc.png)"))
    assert "![](/uploads/abc.png)" in Post.query.one().body
