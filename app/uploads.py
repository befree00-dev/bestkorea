"""본문 이미지 업로드.

- 로그인한 회원만 업로드 가능 (JPG·PNG·GIF·WEBP, 기본 10MB)
- Pillow 로 실제 이미지인지 확인하고, 위치정보 등 메타데이터를 지우고, 너무 크면 줄여서 다시 저장
  (움직이는 GIF 는 애니메이션을 살리기 위해 원본 그대로 저장)
- 파일 이름은 임의 문자열로 바꿔 저장하므로 원래 이름·경로가 노출되지 않음
- 본문에는 '![설명](/uploads/파일이름)' 한 줄로 들어가고, 게시글 화면에서 이미지로 표시된다
"""
import io
import os
import secrets

from flask import Blueprint, abort, current_app, jsonify, request, send_from_directory
from flask_login import current_user, login_required
from PIL import Image, ImageOps, UnidentifiedImageError

bp = Blueprint("uploads", __name__)

FORMATS = {"JPEG": "jpg", "PNG": "png", "GIF": "gif", "WEBP": "webp"}
MAX_SIDE = 2000  # 긴 변 최대 픽셀


class UploadError(Exception):
    pass


def save_image(data, folder):
    """이미지 bytes → 검증·정리 후 저장, 파일 이름 반환."""
    if not data:
        raise UploadError("빈 파일입니다.")
    if len(data) > current_app.config["MAX_IMAGE_BYTES"]:
        raise UploadError(f"이미지는 {current_app.config['MAX_IMAGE_BYTES'] // (1024 * 1024)}MB 이하만 올릴 수 있습니다.")
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()  # 손상·위장 파일 확인
        img = Image.open(io.BytesIO(data))
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise UploadError("이미지 파일이 아니거나 손상된 파일입니다 (JPG·PNG·GIF·WEBP만 가능).")
    fmt = img.format
    if fmt not in FORMATS:
        raise UploadError("JPG·PNG·GIF·WEBP 이미지만 올릴 수 있습니다.")

    os.makedirs(folder, exist_ok=True)
    name = f"{secrets.token_hex(12)}.{FORMATS[fmt]}"
    path = os.path.join(folder, name)

    if fmt == "GIF" and getattr(img, "is_animated", False):
        with open(path, "wb") as f:  # 움직이는 GIF 는 원본 유지 (GIF 에는 위치정보 메타데이터가 없음)
            f.write(data)
        return name

    img = ImageOps.exif_transpose(img)  # 휴대폰 사진 방향 바로잡기
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    if fmt == "JPEG":
        img.convert("RGB").save(out, "JPEG", quality=85, optimize=True)  # EXIF 는 넣지 않음
    elif fmt == "PNG":
        img.save(out, "PNG", optimize=True)
    elif fmt == "WEBP":
        img.save(out, "WEBP", quality=85)
    else:
        img.save(out, "GIF")
    with open(path, "wb") as f:
        f.write(out.getvalue())
    return name


def copy_remote_image(url):
    """외부 이미지(Reddit·X 등)를 내려받아 /uploads 에 저장하고 '/uploads/…' 주소를 돌려준다.
    원본 주소가 나중에 끊겨도 썸네일·본문 이미지가 유지되도록. 실패하면 None (원래 주소를 그대로 씀)."""
    import requests
    from urllib.parse import urljoin

    from .collector.translate import is_public_http_url

    cfg = current_app.config
    session = requests.Session()
    session.headers["User-Agent"] = cfg["ARTICLE_USER_AGENT"]
    try:
        for _ in range(4):
            if not is_public_http_url(url):  # 내부망 주소 차단
                return None
            resp = session.get(url, timeout=15, allow_redirects=False, stream=True)
            if resp.is_redirect:
                url = urljoin(url, resp.headers.get("Location", ""))
                resp.close()
                continue
            if resp.status_code != 200 or not resp.headers.get("Content-Type", "").startswith("image/"):
                resp.close()
                return None
            data = resp.raw.read(cfg["MAX_IMAGE_BYTES"] + 1, decode_content=True)
            resp.close()
            name = save_image(data, cfg["UPLOAD_FOLDER"])  # 크기·형식 검사, 메타데이터 제거, 축소
            return f"/uploads/{name}"
    except (requests.RequestException, UploadError, OSError):
        return None
    return None


@bp.route("/upload/image", methods=["POST"])
@login_required
def upload_image():
    if current_user.is_banned:
        abort(403)
    file = request.files.get("image")
    if file is None:
        return jsonify(error="이미지 파일을 선택하세요."), 400
    try:
        name = save_image(file.read(), current_app.config["UPLOAD_FOLDER"])
    except UploadError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(url=f"/uploads/{name}")


@bp.route("/uploads/<path:name>")
def uploaded(name):
    resp = send_from_directory(current_app.config["UPLOAD_FOLDER"], name, max_age=60 * 60 * 24 * 30)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp
