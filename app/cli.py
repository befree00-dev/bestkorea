import click

from .constants import ROLE_ADMIN, ROLE_OPERATOR, ROLES
from .extensions import db
from .models import User


def register_cli(app):
    @app.cli.command("collect")
    def collect():
        """해외 뉴스/게시물을 한 번 수집해 수집함에 넣습니다."""
        from .collector import run_collection, today_collected_count

        run = run_collection()
        click.echo(f"추가 {run.added}건, 중복 {run.skipped}건, 최근 24시간 수집 {today_collected_count()}건")
        if run.errors:
            click.echo("오류:\n" + run.errors)

    @app.cli.command("make-admin")
    @click.argument("email")
    def make_admin(email):
        """해당 이메일 회원을 관리자로 지정합니다. 기존 관리자는 운영자가 됩니다 (관리자는 1명)."""
        user = User.query.filter_by(email=email.strip().lower()).first()
        if not user:
            raise click.ClickException("회원을 찾을 수 없습니다.")
        for old in User.query.filter(User.role == ROLE_ADMIN, User.id != user.id):
            old.role = ROLE_OPERATOR
            click.echo(f"기존 관리자 {old.username} 님은 운영자로 변경했습니다.")
        user.role = ROLE_ADMIN
        db.session.commit()
        click.echo(f"{user.username} 님을 관리자로 지정했습니다.")

    @app.cli.command("set-role")
    @click.argument("email")
    @click.argument("role", type=click.Choice([r for r in ROLES if r != ROLE_ADMIN]))
    def set_role(email, role):
        """회원 등급을 변경합니다 (operator / reporter / member)."""
        user = User.query.filter_by(email=email.strip().lower()).first()
        if not user:
            raise click.ClickException("회원을 찾을 수 없습니다.")
        if user.role == ROLE_ADMIN:
            raise click.ClickException("관리자의 등급은 make-admin 으로 다른 회원에게 넘겨야 바뀝니다.")
        user.role = role
        db.session.commit()
        click.echo(f"{user.username} 님의 등급을 {ROLES[role]}(으)로 변경했습니다.")

    @app.cli.command("seed-demo")
    def seed_demo():
        """화면 확인용 샘플 데이터를 넣습니다 (운영 DB에서는 사용하지 마세요)."""
        from .demo import seed

        n = seed()
        click.echo(f"샘플 데이터 {n}건을 추가했습니다.")
