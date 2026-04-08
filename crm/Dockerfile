# CRM API (FastAPI). Код в рантайме монтируется из ./crm (см. docker-compose.yml).
# Перезапуск при правках: watchmedo (пакет watchdog) перезапускает uvicorn при изменении *.py.

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY crm/ /app/crm/
COPY google/ /app/google/

ENV PYTHONPATH=/app/google

WORKDIR /app/crm

EXPOSE 8000

CMD ["watchmedo", "auto-restart", "--patterns=*.py", "--recursive", "--directory=/app/crm", "--", "uvicorn", "crm_api:app", "--host", "0.0.0.0", "--port", "8000"]
