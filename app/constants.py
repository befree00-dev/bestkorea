"""게시판·국가 정의."""
from collections import OrderedDict

# slug -> (이름, 종류, 설명)
#   kind="news"      : 해외 반응 카테고리 (관리자·운영자·기자만 작성)
#   kind="community" : 커뮤니티 게시판 (모든 회원 작성)
BOARDS = OrderedDict(
    [
        ("politics", ("정치", "news", "해외 언론이 본 한국 정치·외교·북한 이슈")),
        ("economy", ("경제", "news", "한국 기업·산업·증시·무역 관련 해외 보도")),
        ("entertainment", ("연예", "news", "K-POP, K-드라마, 영화 등 한류 소식과 해외 팬 반응")),
        ("sports", ("스포츠", "news", "해외에서 활약하는 한국 선수와 한국 스포츠 소식")),
        ("game", ("게임", "news", "e스포츠·한국 게임 관련 해외 반응")),
        ("it", ("IT", "news", "한국 IT·테크·반도체·스마트폰·AI 관련 해외 반응")),
        ("society", ("사회", "news", "한국 사회·생활·문화·교육·사건 사고에 대한 해외 반응")),
        ("fun", ("기타", "news", "밈·유머·여행·음식 등 그 밖의 한국 관련 해외 화제")),
        ("humor", ("유머게시판", "community", "웃긴 글, 짤, 썰을 자유롭게")),
        ("free", ("자유게시판", "community", "무엇이든 자유롭게 이야기하세요")),
    ]
)

NEWS_BOARDS = [k for k, v in BOARDS.items() if v[1] == "news"]
COMMUNITY_BOARDS = [k for k, v in BOARDS.items() if v[1] == "community"]

# 출처 지역 code -> (이름, 표시 아이콘)
COUNTRIES = OrderedDict(
    [
        ("na", ("북미", "🇺🇸")),
        ("jp", ("일본", "🇯🇵")),
        ("cn", ("중국", "🇨🇳")),
        ("sea", ("동남아", "🌏")),
        ("eu", ("유럽", "🇪🇺")),
        ("latam", ("남미", "🌎")),
        ("au", ("호주", "🇦🇺")),
        ("af", ("아프리카", "🌍")),
    ]
)

# 예전 코드 → 새 지역 코드 (None = 지역 미지정). 서버 시작 시 기존 데이터에 적용
LEGACY_COUNTRY_MAP = {"us": "na", "reddit": None, "youtube": None, "x": None, "etc": None}

# 언어 → 지역 추정 (가져오기 시 기본값. 영어·스페인어 등 여러 지역에서 쓰는 언어는 추정하지 않음)
LANG_REGION = {
    "ja": "jp", "zh": "cn", "th": "sea", "vi": "sea", "id": "sea", "ms": "sea", "tl": "sea", "fil": "sea",
    "my": "sea", "km": "sea", "lo": "sea", "de": "eu", "fr": "eu", "it": "eu", "nl": "eu", "pl": "eu", "sv": "eu",
    "da": "eu", "fi": "eu", "no": "eu", "nb": "eu", "cs": "eu", "hu": "eu", "ro": "eu", "el": "eu", "uk": "eu",
    "ru": "eu", "sw": "af", "am": "af", "ha": "af", "yo": "af", "zu": "af",
}


def region_for_lang(lang):
    return LANG_REGION.get((lang or "").lower().split("-")[0])


def board_name(slug):
    return BOARDS.get(slug, (slug,))[0]


def country_label(code):
    if code not in COUNTRIES:
        return ""
    name, flag = COUNTRIES[code]
    return f"{flag} {name}"


def country_flag(code):
    return COUNTRIES[code][1] if code in COUNTRIES else ""

# 회원 등급
ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
ROLE_REPORTER = "reporter"
ROLE_MEMBER = "member"
ROLES = OrderedDict(
    [
        (ROLE_ADMIN, "관리자"),
        (ROLE_OPERATOR, "운영자"),
        (ROLE_REPORTER, "기자"),
        (ROLE_MEMBER, "회원"),
    ]
)
# 해외 반응(뉴스) 게시판에 글을 올릴 수 있는 등급
NEWS_ROLES = (ROLE_ADMIN, ROLE_OPERATOR, ROLE_REPORTER)
# 관리자가 부여할 수 있는 등급 (관리자는 1명이므로 제외)
ASSIGNABLE_ROLES = (ROLE_OPERATOR, ROLE_REPORTER, ROLE_MEMBER)


def can_write_board(user, slug):
    if not getattr(user, "is_authenticated", False) or slug not in BOARDS:
        return False
    if BOARDS[slug][1] == "news":
        return user.role in NEWS_ROLES
    return True
