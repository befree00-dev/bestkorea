"""수집 사이트별 검색 설정. 검색어를 추가/수정하려면 이 파일만 고치면 됩니다.

YouTube: 언어별로 한국 관련 검색어를 최근 24시간 영상에서 찾는다.
  - q 에서 | 는 OR (YouTube 검색 문법)
  - relevance_language: 해당 언어 영상을 우선
  - 검색 1회 = API 할당량 100 (하루 무료 10,000). 7개 × 하루 8회 수집 ≈ 5,600
"""

YOUTUBE_QUERIES = [
    dict(q="Korea|Korean|K-pop|Kdrama", relevance_language="en"),
    dict(q="韓国|韓流|K-POP", relevance_language="ja"),
    dict(q="韩国|韓國|韩流", relevance_language="zh-Hans"),
    dict(q="Corea del Sur|coreano|kpop", relevance_language="es"),
    dict(q="Coreia do Sul|coreano|kpop", relevance_language="pt"),
    dict(q="Südkorea|koreanisch", relevance_language="de"),
    dict(q="Corée du Sud|coréen", relevance_language="fr"),
]
