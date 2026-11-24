"""수집 소스 정의.

- Google News RSS 검색: 국가/언어별 현지 포털에 노출된 한국 관련 기사 (when:1d = 최근 24시간)
- Reddit: 한국 관련 서브레딧 + 대형 서브레딧의 한국 키워드 검색 (상위 댓글 = 현지인 반응)

category 를 지정하면 그 카테고리로 고정, None 이면 키워드 분류기가 결정합니다.
소스를 추가/삭제하려면 아래 목록만 수정하면 됩니다.
"""
from urllib.parse import quote_plus


def gnews(query, hl, gl, ceid):
    q = quote_plus(f"{query} when:1d")
    return f"https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"


RSS_SOURCES = [
    # 미국
    dict(id="gn-us", country="us", lang="en", category=None,
         url=gnews('"South Korea" OR Korean', "en-US", "US", "US:en")),
    dict(id="gn-us-kpop", country="us", lang="en", category="entertainment",
         url=gnews('K-pop OR K-drama OR "Korean film"', "en-US", "US", "US:en")),
    dict(id="gn-us-esports", country="us", lang="en", category="game",
         url=gnews('(T1 OR Faker OR LCK OR "Korean game" OR Nexon OR Krafton OR NCSoft)', "en-US", "US", "US:en")),
    dict(id="gn-us-sports", country="us", lang="en", category="sports",
         url=gnews('"Son Heung-min" OR "Lee Kang-in" OR "Kim Min-jae" OR "Korean baseball" OR "Korean golfer"',
                   "en-US", "US", "US:en")),
    # 일본
    dict(id="gn-jp", country="jp", lang="ja", category=None, url=gnews("韓国", "ja", "JP", "JP:ja")),
    dict(id="gn-jp-ent", country="jp", lang="ja", category="entertainment",
         url=gnews("K-POP OR 韓国ドラマ OR 韓流", "ja", "JP", "JP:ja")),
    # 중국·중화권
    dict(id="gn-cn", country="cn", lang="zh", category=None, url=gnews("韩国", "zh-CN", "CN", "CN:zh-Hans")),
    dict(id="gn-tw", country="cn", lang="zh", category=None, url=gnews("韓國", "zh-TW", "TW", "TW:zh-Hant")),
    # 유럽
    dict(id="gn-uk", country="eu", lang="en", category=None, url=gnews('"South Korea"', "en-GB", "GB", "GB:en")),
    dict(id="gn-de", country="eu", lang="de", category=None, url=gnews("Südkorea", "de", "DE", "DE:de")),
    dict(id="gn-fr", country="eu", lang="fr", category=None, url=gnews('"Corée du Sud"', "fr", "FR", "FR:fr")),
    # 남미
    dict(id="gn-br", country="latam", lang="pt", category=None,
         url=gnews('"Coreia do Sul" OR K-pop', "pt-BR", "BR", "BR:pt-419")),
    dict(id="gn-mx", country="latam", lang="es", category=None,
         url=gnews('"Corea del Sur" OR K-pop', "es-419", "MX", "MX:es-419")),
    dict(id="gn-ar", country="latam", lang="es", category=None,
         url=gnews('"Corea del Sur"', "es-419", "AR", "AR:es-419")),
    # 호주
    dict(id="gn-au", country="au", lang="en", category=None, url=gnews('"South Korea" OR Korean', "en-AU", "AU", "AU:en")),
]

# mode: listing(hot/top) 또는 search
REDDIT_SOURCES = [
    dict(id="rd-korea", sub="korea", mode="top", category=None),
    dict(id="rd-worldnews", sub="worldnews", mode="search", query='Korea OR Seoul OR Pyongyang', category="politics"),
    dict(id="rd-economics", sub="economics+stocks+business", mode="search",
         query="Korea OR Samsung OR Hyundai OR SK Hynix OR KOSPI", category="economy"),
    dict(id="rd-kpop", sub="kpop", mode="top", category="entertainment"),
    dict(id="rd-kdrama", sub="kdrama", mode="top", category="entertainment"),
    dict(id="rd-soccer", sub="soccer+baseball+golf", mode="search",
         query='"Son Heung-min" OR Korea OR Korean', category="sports"),
    dict(id="rd-lol", sub="leagueoflegends+starcraft+gaming", mode="search",
         query="T1 OR Faker OR LCK OR Korean OR Korea", category="game"),
    dict(id="rd-fun", sub="funny+memes+mildlyinteresting+interestingasfuck", mode="search",
         query="Korea OR Korean OR Seoul", category="fun"),
]
