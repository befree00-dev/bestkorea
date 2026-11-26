"""다국어 키워드 기반 카테고리 추천 (번역 전 기본값). 키워드가 없으면 기타(fun). 번역하면 Claude 가 다시 고른다."""
import re

KEYWORDS = {
    "entertainment": [
        "k-pop", "kpop", "k-drama", "kdrama", "bts", "blackpink", "newjeans", "aespa", "stray kids", "twice",
        "seventeen", "le sserafim", "ive ", "idol", "drama", "netflix", "film", "movie", "actor", "actress",
        "singer", "album", "concert", "hybe", "sm entertainment", "jyp", "yg entertainment", "squid game",
        "アイドル", "ドラマ", "韓流", "歌手", "俳優", "映画", "偶像", "韩剧", "韓劇", "演员", "演員", "电影", "電影",
        "novela", "dorama", "cantor", "cantora", "película", "filme", "série", "schauspieler", "acteur",
    ],
    "sports": [
        "son heung-min", "heung-min", "kim min-jae", "lee kang-in", "football", "soccer", "baseball", "kbo",
        "golf", "lpga", "olympic", "world cup", "fifa", "tottenham", "psg", "bayern", "match", "tournament",
        "athlete", "skater", "サッカー", "野球", "五輪", "選手", "足球", "棒球", "奥运", "選手", "fútbol", "futebol",
        "béisbol", "fußball", "olympia", "jogador", "jugador",
    ],
    "game": [
        "esports", "e-sports", "t1", "faker", "lck", "league of legends", "starcraft", "nexon", "krafton",
        "ncsoft", "netmarble", "pubg", "lost ark", "maplestory", "gamer", "gaming", "video game", "steam",
        "ゲーム", "eスポーツ", "游戏", "遊戲", "电竞", "電競", "videojuego", "jogo", "spiel",
    ],
    "economy": [
        "economy", "economic", "hyundai", "kia", "kospi", "won ", "export",
        "tariff", "trade", "battery", "stock", "market", "gdp", "inflation",
        "bank of korea", "investment", "経済", "株", "輸出", "関税", "经济", "經濟", "出口",
        "关税", "economía", "economia", "exportación", "wirtschaft", "zoll", "économie", "bourse",
    ],
    "it": [
        "samsung galaxy", "galaxy s", "iphone", "smartphone", "semiconductor", "chip", "sk hynix", "hbm", "memory",
        " ai ", "artificial intelligence", "naver", "kakao", "coupang", "line app", "5g", "robot", "startup",
        "tech", "software", "app ", "internet", "lg display", "oled", "半導体", "スマホ", "アプリ", "半导体",
        "芯片", "手机", "智能", "semiconductores", "tecnología", "tecnologia", "technologie", "halbleiter",
    ],
    "society": [
        "crime", "police", "court", "protest", "strike", "accident", "fire", "school", "education", "university",
        "suicide", "birth rate", "fertility", "population", "aging", "housing", "rent", "gender", "feminism",
        "military service", "conscription", "work hours", "culture", "society", "social", "事件", "事故", "社会",
        "少子化", "教育", "警察", "裁判", "社会", "事故", "人口", "sociedad", "sociedade", "gesellschaft", "société",
    ],
    "fun": [
        "meme", "funny", "lol", "hilarious", "joke", "weird", "cute", "til ", "mildly", "おもしろ", "面白",
        "笑", "搞笑", "有趣", "gracioso", "engraçado", "lustig", "drôle",
    ],
    "politics": [
        "president", "election", "parliament", "assembly", "minister", "north korea", "pyongyang", "kim jong",
        "military", "missile", "diplomat", "summit", "impeach", "policy", "government",
        "大統領", "北朝鮮", "選挙", "国会", "総理", "外交", "总统", "朝鲜", "選舉", "选举", "外交", "presidente",
        "elección", "eleição", "norcorea", "coreia do norte", "corea del norte", "präsident", "nordkorea",
        "président", "corée du nord",
    ],
}

_PATTERNS = {
    cat: [re.compile(re.escape(w)) for w in words] for cat, words in KEYWORDS.items()
}


def classify(text, default="fun"):
    text = f" {(text or '').lower()} "
    scores = {cat: sum(1 for p in pats if p.search(text)) for cat, pats in _PATTERNS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else default
