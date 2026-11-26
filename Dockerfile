FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FLASK_APP=wsgi

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --create-home --uid 1000 app && mkdir -p instance/uploads && chown -R app:app /app
USER app

EXPOSE 8000
# --preload: 테이블 생성을 워커 시작 전에 한 번만 실행
CMD ["gunicorn", "--preload", "--workers", "2", "--timeout", "60", "--bind", "0.0.0.0:8000", "--access-logfile", "-", "wsgi:app"]
