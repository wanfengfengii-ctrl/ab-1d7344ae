FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    HEALTH_ROLE=both

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tests ./tests
COPY scripts ./scripts

EXPOSE 8000

# Web（/health）与 API（/api/health）双健康检查；
# compose 中 web/api 服务会用 HEALTH_ROLE 分别覆盖。
HEALTHCHECK --interval=10s --timeout=4s --start-period=6s --retries=5 \
    CMD python scripts/healthcheck.py http://127.0.0.1:8000 || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host ${APP_HOST} --port ${APP_PORT}"]
