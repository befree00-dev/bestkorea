"""BestKorea 설정. 모든 값은 환경 변수(.env)로 덮어쓸 수 있습니다."""
import os

from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _database_url():
    url = os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "instance", "bestkorea.db"))
    # postgres:// · postgresql:// 형식을 psycopg3 드라이버 형식으로
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


class Config:
    SITE_NAME = os.environ.get("SITE_NAME", "BestKorea")
    SITE_URL = os.environ.get("SITE_URL", "http://localhost:5000").rstrip("/")
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
    # HTTPS 리버스 프록시(nginx 등) 뒤에서 실행할 때 true
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

    # --- 수집함: 운영자가 브라우저에서 가져온 게시물 ---
    MIN_COMMENTS = int(os.environ.get("MIN_COMMENTS", 10))  # 댓글이 이만큼 이상인 글만 받음
    COMMENTS_PER_ITEM = int(os.environ.get("COMMENTS_PER_ITEM", 50))  # 글당 저장·번역할 댓글 수 (인기순)
    # 번역 시 원문 기사 본문을 가져올 때 쓰는 브라우저 User-Agent (일부 언론사는 봇 UA를 차단)
    ARTICLE_USER_AGENT = os.environ.get(
        "ARTICLE_USER_AGENT",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0 Safari/537.36",
    )

    # --- 수집함 '번역' 버튼: Claude API (ANTHROPIC_API_KEY 필요) ---
    ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5")
    ANTHROPIC_EFFORT = os.environ.get("ANTHROPIC_EFFORT", "low")
    ARTICLE_MAX_CHARS = int(os.environ.get("ARTICLE_MAX_CHARS", 60000))  # 번역할 본문 최대 글자 수
    TRANSLATE_SYNC = False  # 테스트용: True 면 번역을 백그라운드가 아닌 요청 안에서 실행


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
    SQLALCHEMY_ENGINE_OPTIONS = {}
    ADMIN_EMAIL = ""
    WTF_CSRF_ENABLED = False
    TRANSLATE_SYNC = True
    SECRET_KEY = "test"
