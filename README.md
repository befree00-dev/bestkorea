# BestKorea

해외 각국(미국·일본·중국·유럽·남미·호주) 포털과 Reddit에서 한국 관련 뉴스와 현지인 반응을 수집해 보여주는 뉴스/커뮤니티 사이트입니다.

## 기능

| 구분 | 내용 |
|---|---|
| 해외 뉴스 게시판 | 정치·사회 / 경제 / 연예 / 스포츠 / 게임 / 기타 (국가별 필터, 최신·추천순, 검색) |
| 커뮤니티 | 유머게시판, 자유게시판 |
| 권한 | **비회원: 모든 글 읽기 가능** · 회원: 글쓰기, 뉴스 제보(원문 링크·국가), 댓글, 추천 |
| 자동 수집 | Google News RSS(15개 국가·언어 피드) + Reddit 8개 소스, 중복 제거, 국가별 고르게 섞기, 24시간 수집량이 목표(기본 10건) 미만이면 수집량 2배 |
| 현지 반응 | Reddit 상위 댓글을 "현지 반응"으로 표시 (자동모더레이터/삭제/NSFW 제외) |
| 번역(선택) | Claude API로 제목·요약·댓글을 한국어로 번역하고 카테고리 분류. 꺼져 있으면 원문 + 다국어 키워드 분류 |
| 수익화 | Google AdSense 슬롯 4곳(상단/사이드바/본문/목록 중간), `ads.txt` 자동 생성, 개인정보처리방침(쿠키·광고 고지) |
| SEO | 페이지별 title/description/OG 태그, canonical, `sitemap.xml`, `robots.txt` |
| 관리자 | 수집 현황(24시간 수집량 vs 목표), 즉시 수집, 수집 오류 로그, 회원 이용 제한 |
| 보안 | 비밀번호 해시, CSRF, 사용자 HTML 미허용(자동 이스케이프), 오픈 리다이렉트 차단 |

## 빠른 시작

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # SECRET_KEY 등 수정
FLASK_APP=wsgi .venv/bin/flask run
```

- http://localhost:5000 접속 → **처음 가입한 회원이 자동으로 관리자**가 됩니다.
- 화면 확인용 샘플 데이터: `FLASK_APP=wsgi .venv/bin/flask seed-demo` (운영 DB에는 사용하지 마세요)
- 수동 수집: `FLASK_APP=wsgi .venv/bin/flask collect`
- 테스트: `.venv/bin/python -m pytest -q`
- 예전 버전에서 키워드 없이 '정치·사회'로 들어간 수집 기사를 '기타'로 옮기기: `FLASK_APP=wsgi .venv/bin/flask reclassify --dry-run`으로 대상 확인 후 `flask reclassify`

## 매일 10건 이상 자동 업데이트

방법 1 — 서버 프로세스가 하나일 때: `.env`에 `ENABLE_SCHEDULER=true` (기본 3시간마다 수집, 시작 1분 후 첫 수집)

방법 2 — gunicorn 다중 워커(권장): 스케줄러는 끄고 cron 사용

```
0 */3 * * * cd /srv/bestkorea && FLASK_APP=wsgi .venv/bin/flask collect >> /var/log/bestkorea-collect.log 2>&1
```

3시간 간격 × 최대 40건이므로 소스 응답이 정상이면 하루 수십 건이 올라갑니다. 관리자 페이지에서 24시간 수집량과 소스별 오류를 확인할 수 있습니다.

수집 소스는 `app/collector/sources.py` 한 파일에서 추가/삭제합니다.

## Docker로 실행 (웹 + 수집기 + PostgreSQL)

Docker Desktop(또는 Docker Engine + Compose)만 있으면 됩니다.

```bash
cp .env.example .env              # ADMIN_EMAIL 등 필요한 값만 수정 (없어도 실행됨)
docker compose up -d --build      # http://localhost:8000
```

| 컨테이너 | 역할 |
|---|---|
| `web` | gunicorn 웹 서버 (포트 8000, `WEB_PORT`로 변경) |
| `collector` | 시작 직후 한 번 수집, 이후 `COLLECT_EVERY_SECONDS`(기본 10800초=3시간)마다 수집 |
| `db` | PostgreSQL 16, 데이터는 `pgdata` 볼륨에 보존 |

자주 쓰는 명령:

```bash
docker compose logs -f collector                 # 수집 로그
docker compose exec web flask collect            # 지금 바로 수집
docker compose exec web flask seed-demo          # 샘플 데이터 (테스트용)
docker compose exec web flask make-admin 이메일    # 관리자 지정
docker compose down                              # 중지 (데이터 유지)
docker compose down -v                           # 중지 + DB 데이터 삭제
```

`.env`에서 `ADMIN_EMAIL`을 지정하면 그 이메일로 가입한 회원만 관리자가 됩니다 (비우면 첫 가입자).
`docker-compose.yml`의 DB 비밀번호는 로컬 테스트용이므로 인터넷에 공개하는 서버에서는 바꾸세요.

## 직접 서버 운영 예시

```bash
.venv/bin/gunicorn -w 3 -b 127.0.0.1:8000 wsgi:app
```

Nginx 등으로 HTTPS 리버스 프록시를 두고 `SESSION_COOKIE_SECURE=true`, `SITE_URL`을 실제 도메인으로 설정하세요. 트래픽이 늘면 `DATABASE_URL`을 PostgreSQL로 바꾸면 됩니다 (`psycopg[binary]` 설치).

## Google AdSense 연결

1. 사이트를 공개 도메인에 배포하고 콘텐츠가 어느 정도 쌓인 뒤 AdSense 신청
2. 승인 후 `.env`에 `ADSENSE_CLIENT=ca-pub-…`와 광고 단위별 슬롯 ID 입력, `SHOW_AD_PLACEHOLDERS=false`
3. `https://도메인/ads.txt`가 자동으로 제공됩니다
4. `/privacy`, `/terms` 페이지의 운영자 연락처 등을 실제 정보로 수정하세요 (AdSense 심사에 필요)

## 선택: Claude 번역

`.env`에 `TRANSLATE_ENABLED=true`, `ANTHROPIC_API_KEY=…` 설정. 새 글 1건당 1회 호출하며(제목+발췌+댓글을 한 번에 번역, 구조화된 JSON 출력), 실패·거절 시에는 원문으로 저장합니다. 기본 모델은 `claude-opus-5-5`(effort `low`)이며, 비용을 줄이려면 `ANTHROPIC_MODEL=claude-haiku-5-5`로 바꿀 수 있습니다.

## 저작권·이용 정책 관련 주의

- 기사 **전문은 저장하지 않습니다.** 제목, 300자 이하 발췌, 원문 링크만 저장합니다.
- Reddit 데이터는 Reddit API 이용약관을 따릅니다. 광고 수익이 있는 상업 사이트는 Reddit의 상업적 이용 조건을 확인하고, 안정적인 수집을 위해 Reddit 앱을 등록해 `REDDIT_CLIENT_ID/SECRET`을 설정하세요 (설정 시 OAuth 엔드포인트 사용).
- Google News RSS는 개인·비상업적 이용을 전제로 합니다. 규모가 커지면 공식 뉴스 API(예: 각 언론사 RSS, 유료 뉴스 API)로 `sources.py`를 교체하는 것을 권장합니다.

## 구조

```
app/
  __init__.py        앱 팩토리, 템플릿 필터, 에러 페이지
  constants.py       게시판·국가 정의
  models.py          User, Post, Reaction(현지 반응), Comment, Like, CollectLog
  views.py           목록/상세/글쓰기/댓글/추천, sitemap·robots·ads.txt
  auth.py admin.py   회원가입·로그인, 관리자
  collector/         sources.py(소스), fetchers.py(RSS·Reddit), classify.py(분류), enrich.py(Claude 번역)
  scheduler.py cli.py
  templates/ static/
tests/               사이트·권한·수집기 테스트 (네트워크 없이 모의 응답 사용)
```
