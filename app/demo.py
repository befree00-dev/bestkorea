"""개발용 샘플 데이터. 실제 기사가 아니며, 화면 구성을 확인하기 위한 용도입니다.

샘플 계정 (비밀번호 모두 demo12345):
  operator@example.com (운영자) / reporter@example.com (기자) / member@example.com (회원)
"""
from datetime import timedelta

from .constants import COMMUNITY_BOARDS, NEWS_BOARDS, ROLE_MEMBER, ROLE_OPERATOR, ROLE_REPORTER
from .extensions import db
from .models import CollectedItem, Comment, Post, Reaction, User, utcnow

COUNTRY_CYCLE = ["na", "jp", "cn", "sea", "eu", "latam", "au", "af"]
SOURCES = {
    "na": "Example Times (US)", "jp": "サンプル新聞", "cn": "示例日报", "sea": "Contoh Harian", "eu": "Beispiel Zeitung",
    "latam": "Diario Ejemplo", "au": "Sample Herald AU", "af": "Sample Daily Nairobi",
}
SAMPLE_COMMENTS = [
    ("user_a", "I visited Seoul last year and this totally matches my experience.", "작년에 서울 갔었는데 내 경험이랑 완전 똑같네.", 512),
    ("user_b", "Interesting perspective, didn't know about this.", "흥미로운 관점이네, 이건 몰랐어.", 233),
    ("user_c", "The comments here are better than the article lol", "기사보다 댓글이 더 재밌네 ㅋㅋ", 98),
]
DEMO_USERS = [
    ("데모운영자", "operator@example.com", ROLE_OPERATOR),
    ("데모기자", "reporter@example.com", ROLE_REPORTER),
    ("데모회원", "member@example.com", ROLE_MEMBER),
]


def _user(name, email, role):
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(username=name, email=email, role=role)
        u.set_password("demo12345")
        db.session.add(u)
        db.session.flush()
    return u


def seed():
    if CollectedItem.query.filter(CollectedItem.url.like("https://example.com/sample/%")).first():
        return 0
    operator, reporter, member = (_user(*u) for u in DEMO_USERS)
    now = utcnow()
    n = 0

    # 해외 반응 게시글 (기자·운영자가 작성)
    for b_i, board in enumerate(NEWS_BOARDS):
        for i in range(3):
            country = COUNTRY_CYCLE[(b_i + i) % len(COUNTRY_CYCLE)]
            post = Post(
                board=board, user_id=(reporter if i % 2 == 0 else operator).id,
                title=f"[샘플] {SOURCES[country]}가 본 한국 #{b_i * 3 + i + 1}",
                original_title=f"[Sample] How {SOURCES[country]} sees Korea #{b_i * 3 + i + 1}",
                body="화면 확인용 샘플 기사입니다. 실제로는 수집함에서 번역한 본문이 들어갑니다.",
                source_url=f"https://example.com/sample/post/{board}/{i}", source_name=SOURCES[country],
                country=country, lang="en", views=(i + 1) * 37, like_count=i * 3,
                created_at=now - timedelta(hours=b_i * 3 + i),
            )
            for pos, (author, body, ko, score) in enumerate(SAMPLE_COMMENTS):
                post.reactions.append(Reaction(position=pos, author=author, body=body, body_ko=ko, score=score))
            db.session.add(post)
            n += 1

    # 커뮤니티 게시글 (일반 회원)
    for board in COMMUNITY_BOARDS:
        for i in range(3):
            post = Post(board=board, title=f"[샘플] {board} 게시판 테스트 글 {i + 1}",
                        body="회원이 작성한 글 예시입니다.\n줄바꿈도 표시됩니다.", user_id=member.id,
                        created_at=now - timedelta(hours=i * 5))
            db.session.add(post)
            db.session.flush()
            db.session.add(Comment(post_id=post.id, user_id=reporter.id, body="샘플 댓글입니다."))
            post.comment_count = 1
            n += 1

    # 수집함 (아직 게시되지 않은 수집 글) — YouTube 샘플
    channels = ["Example Reacts", "サンプルチャンネル", "示例频道", "Canal Ejemplo", "Beispiel Kanal"]
    for i in range(8):
        item = CollectedItem(
            source_type="youtube", source_id=f"demo{i:07d}",
            url=f"https://www.youtube.com/watch?v=demo{i:07d}",
            title=f"[Sample] Foreigners react to Korea #{i + 1}",
            snippet="Sample video description for layout testing.",
            source_name=channels[i % len(channels)], country=COUNTRY_CYCLE[i % len(COUNTRY_CYCLE)], lang="en",
            category_hint=NEWS_BOARDS[i % len(NEWS_BOARDS)],
            num_comments=1200 - i * 130,
            comments=[dict(author=a, body=b, score=sc) for a, b, _, sc in SAMPLE_COMMENTS],
            collected_at=now - timedelta(minutes=i * 10),
        )
        if i == 0:  # 번역까지 끝난 예시
            item.translate_status = "done"
            item.translated_at = now
            item.title_ko = "[샘플] 해외 언론이 본 한국 #1"
            item.summary_ko = "번역 버튼을 누르면 이 자리에 원문 본문 전체의 번역이 들어갑니다."
            item.category_ko = item.category_hint
        db.session.add(item)
        n += 1

    db.session.commit()
    return n
