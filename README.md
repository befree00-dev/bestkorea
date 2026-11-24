# BestKorea

해외 각국(미국·일본·중국·유럽·남미·호주) 언론과 커뮤니티의 한국 관련 뉴스와 현지인 반응을 소개하는 뉴스/커뮤니티 사이트입니다.
**모든 게시물은 사람이 직접 올립니다.** 수집기는 관리자·운영자 전용 '수집함'에 후보 글을 모아 주고, 운영자가 번역 버튼으로 요약·번역한 뒤 다듬어 게시합니다.

## 회원 등급

| 등급 | 해외 반응 게시판 | 커뮤니티 게시판 | 수집함 | 관리 |
|---|---|---|---|---|
| 관리자 (1명) | 작성 | 작성 | 사용 | 회원 등급 지정, 기자 지원 승인, 이용 제한, 모든 글 삭제 |
| 운영자 | 작성 | 작성 | 사용 | - |
| 기자 | 작성 | 작성 | - | - |
| 회원 | - (기자 지원 가능) | 작성 | - | - |
| 비회원 | 읽기 | 읽기 | - | - |

- 관리자: `ADMIN_EMAIL`로 가입한 회원 (비우면 첫 가입자). 관리자 넘기기는 서버에서 `flask make-admin 이메일` (기존 관리자는 운영자가 됨)
- 운영자: 관리자 페이지 → 회원 등급 관리에서 지정
- 기자: 회원이 해외 반응 게시판의 **기자 지원하기**로 지원 → 관리자 페이지에서 승인

## 기능

| 구분 | 내용 |
|---|---|
| 해외 반응 게시판 | 정치·사회 / 경제 / 연예 / 스포츠 / 게임 / 기타 (국가별 필터, 최신·추천순, 검색), 원문 링크·대표 이미지·현지 반응(번역 댓글) |
| 커뮤니티 | 유머게시판, 자유게시판 |
| 수집함 (관리자·운영자) | Google News RSS(15개 국가·언어) + Reddit 8개 소스(API 키가 있을 때만, **댓글 10개 이상 글만**, 인기 댓글 최대 50개). 상태(새 글/게시됨/숨김)·출처·국가 필터 |
| 번역 버튼 | 글 상단·하단. 원문 기사 본문과 대표 이미지를 가져와 Claude로 **500자 이내 요약**, **댓글 전체 번역**(하단 배치), 카테고리 추천 → **게시글로 작성**하면 번역 내용이 채워진 글쓰기 화면으로 이동 |
| 수익화 | Google AdSense 슬롯 4곳, `ads.txt` 자동 생성, 개인정보처리방침(쿠키·광고 고지) |
| SEO | 페이지별 title/description/OG 태그, canonical, `sitemap.xml`, `robots.txt` |
| 보안 | 비밀번호 해시, CSRF, 사용자 HTML 미허용, 오픈 리다이렉트 차단, 원문 가져오기 시 내부망 주소 차단 |

## 운영 흐름

1. 수집기가 3시간마다 후보 글을 **수집함**에 넣음 (사이트에는 게시되지 않음)
2. 운영자가 수집함에서 글을 열고 **번역** 클릭 → 수십 초 뒤 한국어 제목, 500자 요약, 이미지, 번역 댓글 표시
3. **게시글로 작성** → 제목·요약·원문 링크·이미지·카테고리가 채워진 글쓰기 화면에서 다듬어 등록
4. 번역된 댓글은 게시글의 "현지 반응"으로 함께 올라가고, 수집함 글은 '게시됨'으로 바뀜

## 빠른 시작

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # SECRET_KEY 등 수정
FLASK_APP=wsgi .venv/bin/flask run
```

- http://localhost:5000 접속 → `ADMIN_EMAIL`(비우면 첫 가입자)로 가입한 회원이 관리자가 됩니다.
- 화면 확인용 샘플 데이터: `FLASK_APP=wsgi .venv/bin/flask seed-demo` — 운영자·기자·회원 샘플 계정(비밀번호 `demo12345`)과 수집함 샘플이 생깁니다. 운영 DB에는 사용하지 마세요.
- 수동 수집: `FLASK_APP=wsgi .venv/bin/flask collect`
- 등급 변경(CLI): `flask set-role 이메일 operator|reporter|member`, 관리자 넘기기: `flask make-admin 이메일`
- 테스트: `.venv/bin/python -m pytest -q`

## 수집 주기

방법 1 — 서버 프로세스가 하나일 때: `.env`에 `ENABLE_SCHEDULER=true` (기본 3시간마다 수집, 시작 1분 후 첫 수집)

방법 2 — gunicorn 다중 워커(권장): 스케줄러는 끄고 cron 사용

```
0 */3 * * * cd /srv/bestkorea && FLASK_APP=wsgi .venv/bin/flask collect >> /var/log/bestkorea-collect.log 2>&1
```

3시간 간격 × 최대 40건이므로 소스 응답이 정상이면 하루 수십 건이 수집함에 쌓입니다. 관리자 페이지에서 24시간 수집량과 소스별 오류를 확인할 수 있습니다.

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
docker compose exec web flask make-admin 이메일    # 관리자 넘기기
docker compose exec web flask set-role 이메일 operator   # 운영자 지정
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

## 번역 버튼 설정 (Claude API)

`.env`에 `ANTHROPIC_API_KEY=…`를 넣으면 수집함의 **번역** 버튼이 동작합니다. 키가 없으면 버튼을 눌렀을 때 오류 안내가 표시됩니다.

- 1회 클릭 = Claude 호출 1회 (제목 번역 + 본문 요약 + 카테고리 + 댓글 전체 번역을 한 번에, 구조화된 JSON 출력)
- 기본 모델 `claude-opus-5-5`, effort `low`. 비용을 줄이려면 `ANTHROPIC_MODEL=claude-haiku-5-5`
- 원문 본문을 못 가져오면(유료벽, 차단 등) 수집된 제목·발췌만으로 요약하고 화면에 그 사실을 표시합니다
- 요약 길이 `SUMMARY_MAX_CHARS`(기본 500), 댓글 수 `COMMENTS_PER_ITEM`(기본 50)

## 저작권·이용 정책 관련 주의

- 기사 **전문은 저장하지 않습니다.** 번역 시 원문을 읽어 요약만 저장하고, 게시글에는 요약과 원문 링크를 싣습니다.
- 원문 기사의 대표 이미지는 저작권이 원 매체에 있습니다. 게시 전에 사용 가능 여부를 확인하세요 (글쓰기 화면에서 이미지 주소를 지울 수 있습니다).
- Reddit은 키 없는 자동 요청을 차단(403)하므로 **`REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET`이 있을 때만 Reddit을 수집**합니다 (OAuth 엔드포인트 사용). 키가 없으면 Google News만 수집하며, 관리자 페이지에 Reddit 상태가 표시됩니다. Reddit 데이터는 Reddit API 이용약관을 따르며, 광고 수익이 있는 사이트는 상업적 이용 조건도 확인하세요.
- Google News RSS는 개인·비상업적 이용을 전제로 합니다. 규모가 커지면 공식 뉴스 API(예: 각 언론사 RSS, 유료 뉴스 API)로 `sources.py`를 교체하는 것을 권장합니다.

## 구조

```
app/
  __init__.py        앱 팩토리, 템플릿 필터, 에러 페이지
  constants.py       게시판·국가·회원 등급 정의, 게시 권한
  models.py          User(등급), ReporterApplication, Post, Reaction(현지 반응), Comment, Like,
                     CollectedItem(수집함), CollectLog
  views.py           목록/상세/글쓰기(수집함에서 작성 포함)/댓글/추천, 기자 지원, sitemap·robots·ads.txt
  desk.py            수집함 (관리자·운영자): 목록, 상세, 번역 버튼, 숨기기
  admin.py           관리자: 등급 관리, 기자 지원 승인, 수집 기록
  auth.py            회원가입·로그인
  collector/         sources.py(소스), fetchers.py(RSS·Reddit), classify.py(분류),
                     translate.py(원문 추출 + Claude 요약·번역)
  scheduler.py cli.py
  templates/ static/
collect_loop.py      Docker 수집기 컨테이너용 반복 수집
tests/               권한·수집·번역 테스트 (네트워크 없이 모의 응답 사용)
```
