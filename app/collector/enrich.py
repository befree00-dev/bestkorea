"""선택 기능: Claude API로 외국어 제목/요약/현지 반응을 한국어로 번역하고 카테고리를 분류.

TRANSLATE_ENABLED=true 와 ANTHROPIC_API_KEY 가 있을 때만 동작합니다.
실패하거나 거절(refusal)되면 None 을 반환하고, 원문 + 키워드 분류로 저장됩니다.
"""
import logging
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

Category = Literal["politics", "economy", "entertainment", "sports", "game", "fun"]

SYSTEM = (
    "당신은 해외 언론과 커뮤니티의 한국 관련 콘텐츠를 한국 독자에게 소개하는 뉴스 에디터입니다. "
    "외국어 제목·발췌·댓글을 자연스러운 한국어로 옮깁니다. 의역은 하되 원문에 없는 사실을 덧붙이지 마세요. "
    "제목은 60자 이내의 기사 제목체로, 요약은 1~2문장으로 작성합니다. 원문이 짧아 요약할 내용이 없으면 빈 문자열을 반환하세요. "
    "댓글 번역은 입력 순서와 개수를 그대로 유지하고, 인터넷 말투의 뉘앙스를 살려 반말/구어체로 번역합니다. "
    "카테고리: politics(정치·사회·외교·북한), economy(경제·기업·산업), entertainment(K-POP·드라마·영화·연예), "
    "sports(스포츠), game(게임·e스포츠), fun(밈·유머·가벼운 화제)."
)


class Enriched(BaseModel):
    title_ko: str = Field(description="한국어 제목")
    summary_ko: str = Field(description="한국어 1~2문장 요약, 없으면 빈 문자열")
    category: Category
    reactions_ko: list[str] = Field(description="댓글 한국어 번역, 입력과 같은 순서/개수")


_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def enrich(item, model):
    reactions = "\n".join(f"[{i + 1}] {r['body']}" for i, r in enumerate(item.reactions)) or "(없음)"
    prompt = (
        f"출처: {item.source_name} (언어: {item.lang})\n"
        f"제목: {item.title}\n"
        f"발췌: {item.summary or '(없음)'}\n\n"
        f"댓글 {len(item.reactions)}개:\n{reactions}"
    )
    try:
        response = _get_client().beta.messages.parse(
            model=model,
            max_tokens=16000,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_format=Enriched,
            output_config={"effort": "low"},
            # 안전 분류기가 거절하면 서버가 다른 모델로 자동 재시도
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.RateLimitError as exc:
        log.warning("Claude rate limited, skip translation: %s", exc)
        return None
    except anthropic.APIStatusError as exc:
        log.warning("Claude API error %s, skip translation: %s", exc.status_code, exc)
        return None
    except anthropic.APIConnectionError as exc:
        log.warning("Claude connection error, skip translation: %s", exc)
        return None

    if response.stop_reason == "refusal" or response.parsed_output is None:
        log.info("translation declined/empty for %s", item.url)
        return None
    result = response.parsed_output
    if len(result.reactions_ko) != len(item.reactions):
        result.reactions_ko = []  # 순서가 어긋나면 번역 반응은 버림
    return result
