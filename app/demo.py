"""개발용 샘플 데이터. 실제 기사가 아니며, 화면 구성을 확인하기 위한 용도입니다."""
from datetime import timedelta

from .constants import COMMUNITY_BOARDS, NEWS_BOARDS
from .extensions import db
from .models import Comment, Post, Reaction, User, utcnow

COUNTRY_CYCLE = ["us", "jp", "cn", "eu", "latam", "au", "reddit"]
SOURCES = {
    "us": "Example Times (US)", "jp": "サンプル新聞", "cn": "示例日报", "eu": "Beispiel Zeitung",
    "latam": "Diario Ejemplo", "au": "Sample Herald AU", "reddit": "r/korea",
}
SAMPLE_REACTIONS = [
    ("user_a", "I visited Seoul last year and this totally matches my experience.", "작년에 서울 갔었는데 내 경험이랑 완전 똑같네.", 512),
    ("user_b", "Interesting perspective, didn't know about this.", "흥미로운 관점이네, 이건 몰랐어.", 233),
    ("user_c", "The comments here are better than the article lol", "기사보다 댓글이 더 재밌네 ㅋㅋ", 98),
]


def seed():
    if Post.query.filter(Post.source_url.like("https://example.com/sample/%")).first():
        return 0
    demo = User.query.filter_by(email="demo@example.com").first()
    if not demo:
        demo = User(username="데모회원", email="demo@example.com")
        demo.set_password("demo12345")
        db.session.add(demo)
        db.session.flush()

    now = utcnow()
    n = 0
    for b_i, board in enumerate(NEWS_BOARDS):
        for i in range(4):
            country = COUNTRY_CYCLE[(b_i + i) % len(COUNTRY_CYCLE)]
            post = Post(
                board=board,
                title=f"[샘플] {SOURCES[country]}가 본 한국 #{b_i * 4 + i + 1}",
                original_title=f"[Sample] How {SOURCES[country]} sees Korea #{b_i * 4 + i + 1}",
                body="이 글은 화면 확인용 샘플입니다. 실제 수집 시에는 원문 기사의 짧은 발췌와 링크가 표시됩니다.",
                source_url=f"https://example.com/sample/{board}/{i}",
                source_name=SOURCES[country],
                country=country,
                lang="en",
                views=(i + 1) * 37,
                like_count=i * 3,
                created_at=now - timedelta(hours=b_i * 3 + i),
                published_at=now - timedelta(hours=b_i * 3 + i + 1),
            )
            if country == "reddit":
                for author, body, ko, score in SAMPLE_REACTIONS:
                    post.reactions.append(Reaction(author=author, body=body, body_ko=ko, score=score))
            db.session.add(post)
            n += 1
    for board in COMMUNITY_BOARDS:
        for i in range(3):
            post = Post(
                board=board, title=f"[샘플] {board} 게시판 테스트 글 {i + 1}",
                body="회원이 작성한 글 예시입니다.\n줄바꿈도 표시됩니다.", user_id=demo.id,
                created_at=now - timedelta(hours=i * 5),
            )
            db.session.add(post)
            db.session.flush()
            db.session.add(Comment(post_id=post.id, user_id=demo.id, body="샘플 댓글입니다."))
            post.comment_count = 1
            n += 1
    db.session.commit()
    return n
