"""Docker 수집기 컨테이너용: 시작하자마자 한 번 수집하고 COLLECT_EVERY_SECONDS(기본 3시간)마다 반복."""
import logging
import os
import time

from app import create_app
from app.collector import SITES, run_collection, today_counts

INTERVAL = int(os.environ.get("COLLECT_EVERY_SECONDS", 10800))

app = create_app()
log = logging.getLogger("collector")

while True:
    with app.app_context():
        try:
            run = run_collection()
            counts = ", ".join(f"{SITES[k]['name']} {v}" for k, v in today_counts().items())
            log.info("추가 %s건, 교체 %s건 / 오늘 수집함: %s", run.added, run.skipped, counts)
            if run.errors:
                log.warning("수집 오류 %s건 (관리자 페이지에서 확인)", len(run.errors.splitlines()))
        except Exception:
            log.exception("수집 실패")
    time.sleep(INTERVAL)
