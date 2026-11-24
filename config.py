"""BestKorea 설정. 모든 값은 환경 변수(.env)로 덮어쓸 수 있습니다."""
import os

from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _database_url():
    url = os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "instance", "bestkorea.db"))
    # Render/Heroku 형식(postgres://, postgresql://)을 psycopg3 드라이버 형식으로
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


class Config:
    SITE_NAME = os.environ.get("SITE_NAME", "BestKorea")
    # Render 는 RENDER_EXTERNAL_URL(https://xxx.onrender.com)을 자동으로 넣어준다
    SITE_URL = (
        os.environ.get("SITE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "http://localhost:5000"
    ).rstrip("/")
    SITE_DESCRIPTION = os.environ.get(
        "SITE_DESCRIPTION",
        "해외에서 본 한국 - 미국·일본·중국·유럽·남미·호주 언론과 Reddit의 한국 관련 뉴스와 현지 반응",
    )

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_TIME_LIMIT = None
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    # HTTPS 리버스 프록시(Render, nginx) 뒤에서 실행할 때 true
    BEHIND_PROXY = _bool("BEHIND_PROXY", False)
    # 이 이메일로 가입한 회원이 관리자가 됨. 비워 두면 첫 번째 가입자가 관리자
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip().lower()

    POSTS_PER_PAGE = int(os.environ.get("POSTS_PER_PAGE", 20))

    # --- Google AdSense ---
    # 예: ca-pub-1234567890123456 (비워 두면 광고 대신 자리표시만 보임)
    ADSENSE_CLIENT = os.environ.get("ADSENSE_CLIENT", "")
    ADSENSE_SLOT_TOP = os.environ.get("ADSENSE_SLOT_TOP", "")
    ADSENSE_SLOT_SIDEBAR = os.environ.get("ADSENSE_SLOT_SIDEBAR", "")
    ADSENSE_SLOT_IN_ARTICLE = os.environ.get("ADSENSE_SLOT_IN_ARTICLE", "")
    ADSENSE_SLOT_IN_FEED = os.environ.get("ADSENSE_SLOT_IN_FEED", "")
    SHOW_AD_PLACEHOLDERS = _bool("SHOW_AD_PLACEHOLDERS", True)
    GOOGLE_ANALYTICS_ID = os.environ.get("GOOGLE_ANALYTICS_ID", "")

    # --- 자동 수집 ---
    ENABLE_SCHEDULER = _bool("ENABLE_SCHEDULER", False)
    COLLECT_INTERVAL_MINUTES = int(os.environ.get("COLLECT_INTERVAL_MINUTES", 180))
    COLLECT_MAX_PER_SOURCE = int(os.environ.get("COLLECT_MAX_PER_SOURCE", 4))
    COLLECT_MAX_PER_RUN = int(os.environ.get("COLLECT_MAX_PER_RUN", 40))
    DAILY_TARGET = int(os.environ.get("DAILY_TARGET", 10))
    REACTIONS_PER_POST = int(os.environ.get("REACTIONS_PER_POST", 8))
    HTTP_USER_AGENT = os.environ.get("HTTP_USER_AGENT", "web:bestkorea-collector:1.0")
    REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
    REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")

    # --- 선택: Claude로 제목/요약/반응 한국어 번역 + 카테고리 분류 ---
    TRANSLATE_ENABLED = _bool("TRANSLATE_ENABLED", False)
    ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5")


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
    SQLALCHEMY_ENGINE_OPTIONS = {}
    ADMIN_EMAIL = ""
    WTF_CSRF_ENABLED = False
    ENABLE_SCHEDULER = False
    TRANSLATE_ENABLED = False
    SECRET_KEY = "test"
