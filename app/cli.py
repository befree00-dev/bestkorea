import click

from .extensions import db
from .models import User


def register_cli(app):
    @app.cli.command("collect")
    def collect():
        """해외 뉴스/반응을 한 번 수집합니다."""
        from .collector import run_collection, today_news_count

        run = run_collection()
        click.echo(f"추가 {run.added}건, 중복 {run.skipped}건, 최근 24시간 {today_news_count()}건")
        if run.errors:
            click.echo("오류:\n" + run.errors)

    @app.cli.command("reclassify")
    @click.option("--dry-run", is_flag=True, help="옮기지 않고 대상만 보여줍니다.")
    def reclassify(dry_run):
        """키워드 없이 '정치·사회'로 들어간 기존 수집 기사를 '기타'로 옮깁니다."""
        from .collector import reclassify_fallback_politics

        moved = reclassify_fallback_politics(dry_run=dry_run)
        for p in moved:
            click.echo(f"  #{p.id} {p.title[:60]}")
        verb = "옮길 대상" if dry_run else "'기타'로 옮김"
        click.echo(f"{verb}: {len(moved)}건")

    @app.cli.command("make-admin")
    @click.argument("email")
    def make_admin(email):
        """해당 이메일 회원을 관리자로 지정합니다."""
        user = User.query.filter_by(email=email.lower()).first()
        if not user:
            raise click.ClickException("회원을 찾을 수 없습니다.")
        user.is_admin = True
        db.session.commit()
        click.echo(f"{user.username} 님을 관리자로 지정했습니다.")

    @app.cli.command("seed-demo")
    def seed_demo():
        """화면 확인용 샘플 데이터를 넣습니다 (운영 DB에서는 사용하지 마세요)."""
        from .demo import seed

        n = seed()
        click.echo(f"샘플 게시글 {n}개를 추가했습니다.")
