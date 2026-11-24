"""웹 프로세스 내장 스케줄러 (단일 프로세스 배포용).

gunicorn 워커가 여러 개면 중복 실행되므로, 그 경우 ENABLE_SCHEDULER=false 로 두고
cron 에서 `flask collect` 를 호출하세요 (README 참고).
"""
import logging
import os
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

log = logging.getLogger(__name__)
_scheduler = None


def start_scheduler(app):
    global _scheduler
    # Flask 디버그 리로더의 부모 프로세스에서는 시작하지 않음
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    if _scheduler:
        return

    def job():
        from .collector import run_collection

        with app.app_context():
            try:
                run_collection()
            except Exception:
                log.exception("scheduled collection failed")

    _scheduler = BackgroundScheduler(daemon=True)
    # 서버 시작 1분 뒤 첫 수집, 이후 주기 실행
    _scheduler.add_job(job, "interval", minutes=app.config["COLLECT_INTERVAL_MINUTES"], id="collect",
                       next_run_time=datetime.now() + timedelta(minutes=1), max_instances=1, coalesce=True)
    _scheduler.start()
    log.info("collector scheduler started (every %s min)", app.config["COLLECT_INTERVAL_MINUTES"])
