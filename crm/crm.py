"""
Точка входа мини-CRM: запуск HTTP API (FastAPI + SQLite).

Переменная окружения CRM_DB_PATH — путь к файлу базы (по умолчанию crm.sqlite3 в текущей папке).

Запуск:
    python crm.py
    uvicorn crm_api:app --reload
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

import uvicorn


def main() -> None:
    host = os.environ.get("CRM_HOST", "127.0.0.1")
    port = int(os.environ.get("CRM_PORT", "8000"))
    uvicorn.run("crm_api:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
