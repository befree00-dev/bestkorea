"""게시판·국가 정의."""
from collections import OrderedDict

# slug -> (이름, 종류, 설명)
#   kind="news"      : 해외 뉴스 카테고리 (자동 수집 + 회원 제보)
#   kind="community" : 회원 커뮤니티 게시판
BOARDS = OrderedDict(
    [
        ("politics", ("정치·사회", "news", "해외 언론이 본 한국 정치·외교·사회 이슈")),
        ("economy", ("경제", "news", "한국 기업·산업·증시·무역 관련 해외 보도")),
        ("entertainment", ("연예", "news", "K-POP, K-드라마, 영화 등 한류 소식과 해외 팬 반응")),
        ("sports", ("스포츠", "news", "해외에서 활약하는 한국 선수와 한국 스포츠 소식")),
        ("game", ("게임", "news", "e스포츠·한국 게임 관련 해외 반응")),
        ("fun", ("기타", "news", "밈·유머·생활·여행 등 그 밖의 한국 관련 해외 화제")),
        ("humor", ("유머게시판", "community", "웃긴 글, 짤, 썰을 자유롭게")),
        ("free", ("자유게시판", "community", "무엇이든 자유롭게 이야기하세요")),
    ]
)

NEWS_BOARDS = [k for k, v in BOARDS.items() if v[1] == "news"]
COMMUNITY_BOARDS = [k for k, v in BOARDS.items() if v[1] == "community"]

# code -> (이름, 국기)
COUNTRIES = OrderedDict(
    [
        ("us", ("미국", "🇺🇸")),
        ("jp", ("일본", "🇯🇵")),
        ("cn", ("중국·중화권", "🇨🇳")),
        ("eu", ("유럽", "🇪🇺")),
        ("latam", ("남미", "🌎")),
        ("au", ("호주", "🇦🇺")),
        ("reddit", ("Reddit", "👽")),
        ("etc", ("기타", "🌐")),
    ]
)


def board_name(slug):
    return BOARDS.get(slug, (slug,))[0]


def country_label(code):
    name, flag = COUNTRIES.get(code or "etc", COUNTRIES["etc"])
    return f"{flag} {name}"
