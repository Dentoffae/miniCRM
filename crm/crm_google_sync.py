"""
Полная выгрузка данных CRM (SQLite) в Google Таблицу на Google Drive.

Используется GoogleSheetsClient (сервисный аккаунт) из папки google/.
Нужны в .env: GOOGLE_SPREADSHEET_ID, GOOGLE_APPLICATION_CREDENTIALS (путь к JSON ключа).

Создаются/используются листы (имена настраиваются через CRM_GOOGLE_TAB_*):
  CRM_Clients, CRM_Deals, CRM_Tasks — при отсутствии листы добавляются в таблицу.

Таблицу нужно заранее создать в Drive и выдать сервисному аккаунту доступ «Редактор»
(или расшарить файл на email из client_email в JSON ключа).
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass

_GOOGLE_DIR = _REPO_ROOT / "google"
if _GOOGLE_DIR.is_dir() and str(_GOOGLE_DIR) not in sys.path:
    sys.path.insert(0, str(_GOOGLE_DIR))

from crm_database import CRMStore  # noqa: E402

try:
    from google_sheets_crud import GoogleSheetsClient  # noqa: E402
except ImportError as e:  # pragma: no cover
    GoogleSheetsClient = None  # type: ignore[misc, assignment]
    _import_error = e
else:
    _import_error = None

log = logging.getLogger(__name__)

SHEET_CLIENTS = os.environ.get("CRM_GOOGLE_TAB_CLIENTS", "CRM_Clients")
SHEET_DEALS = os.environ.get("CRM_GOOGLE_TAB_DEALS", "CRM_Deals")
SHEET_TASKS = os.environ.get("CRM_GOOGLE_TAB_TASKS", "CRM_Tasks")


def _credentials_path() -> Path | None:
    raw = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip().strip('"').strip("'")
    if not raw:
        return None
    p = Path(raw)
    if p.is_file():
        return p.resolve()
    p2 = _REPO_ROOT / raw
    if p2.is_file():
        return p2.resolve()
    # ключ часто лежит в google/, а в .env остался путь к корню проекта
    p3 = _REPO_ROOT / "google" / p.name
    if p3.is_file():
        return p3.resolve()
    # Docker/Linux: в .env часто остаётся Windows-путь — ключ смонтирован в /app/google
    docker_key = Path("/app/google") / p.name
    if docker_key.is_file():
        return docker_key.resolve()
    return None


def google_sync_configured() -> bool:
    if GoogleSheetsClient is None:
        return False
    sid = os.environ.get("GOOGLE_SPREADSHEET_ID", "").strip().strip('"').strip("'")
    return bool(sid and _credentials_path())


def _a1_quote(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def _ensure_tabs(gs: GoogleSheetsClient) -> None:
    existing = set(gs.list_sheet_titles())
    req: list[dict[str, Any]] = []
    for t in (SHEET_CLIENTS, SHEET_DEALS, SHEET_TASKS):
        if t not in existing:
            req.append({"addSheet": {"properties": {"title": t}}})
    if req:
        gs.spreadsheet_batch_update(req)


def _build_rows(store: CRMStore) -> tuple[list[list[Any]], list[list[Any]], list[list[Any]]]:
    clients = store.client_list(limit=50_000, offset=0)
    ch = ["id", "name", "email", "phone", "company", "notes", "status", "created_at", "updated_at"]
    cr = [ch]
    for c in clients:
        cr.append(
            [
                c.id,
                c.name,
                c.email or "",
                c.phone or "",
                c.company or "",
                c.notes or "",
                c.status,
                c.created_at or "",
                c.updated_at or "",
            ]
        )

    deals = store.deal_list(limit=50_000, offset=0)
    dh = [
        "id",
        "client_id",
        "title",
        "description",
        "amount",
        "currency",
        "status",
        "order_number",
        "created_at",
        "updated_at",
    ]
    dr = [dh]
    for d in deals:
        dr.append(
            [
                d.id,
                d.client_id if d.client_id is not None else "",
                d.title,
                d.description or "",
                d.amount if d.amount is not None else "",
                d.currency,
                d.status,
                d.order_number or "",
                d.created_at or "",
                d.updated_at or "",
            ]
        )

    tasks = store.task_list(limit=50_000, offset=0)
    th = [
        "id",
        "client_id",
        "deal_id",
        "title",
        "description",
        "due_at",
        "completed",
        "created_at",
        "updated_at",
    ]
    tr = [th]
    for t in tasks:
        tr.append(
            [
                t.id,
                t.client_id if t.client_id is not None else "",
                t.deal_id if t.deal_id is not None else "",
                t.title,
                t.description or "",
                t.due_at or "",
                "yes" if t.completed else "no",
                t.created_at or "",
                t.updated_at or "",
            ]
        )
    return cr, dr, tr


def sync_crm_to_google_sheets(store: CRMStore) -> dict[str, Any]:
    """
    Полностью перезаписывает три листа снимком из SQLite.
    Raises ValueError если не настроено окружение; HttpError при ошибке API.
    """
    if GoogleSheetsClient is None:
        raise ValueError(f"Не удалось импортировать google_sheets_crud: {_import_error}")
    if not google_sync_configured():
        raise ValueError(
            "Задайте GOOGLE_SPREADSHEET_ID и GOOGLE_APPLICATION_CREDENTIALS (путь к JSON сервисного аккаунта)."
        )
    cred_path = _credentials_path()
    if not cred_path:
        raise ValueError("Файл ключа GOOGLE_APPLICATION_CREDENTIALS не найден.")
    sid = os.environ["GOOGLE_SPREADSHEET_ID"].strip().strip('"').strip("'")
    gs = GoogleSheetsClient(sid, credentials_path=str(cred_path))
    _ensure_tabs(gs)

    rows_c, rows_d, rows_t = _build_rows(store)

    def push(title: str, values: list[list[Any]]) -> None:
        quoted = _a1_quote(title)
        gs.clear_range(f"{quoted}!A:ZZ")
        gs.update_range(f"{quoted}!A1", values)

    push(SHEET_CLIENTS, rows_c)
    push(SHEET_DEALS, rows_d)
    push(SHEET_TASKS, rows_t)

    return {
        "spreadsheet_id": sid,
        "tabs": {"clients": SHEET_CLIENTS, "deals": SHEET_DEALS, "tasks": SHEET_TASKS},
        "counts": {
            "clients": max(0, len(rows_c) - 1),
            "deals": max(0, len(rows_d) - 1),
            "tasks": max(0, len(rows_t) - 1),
        },
    }


def sync_crm_to_google_after_write(store: CRMStore) -> None:
    """После CRUD в CRM: выгрузка в Sheets. Ошибки только в лог, API не падает."""
    if os.environ.get("CRM_GOOGLE_SYNC", "1").strip().lower() in ("0", "false", "no"):
        return
    if not google_sync_configured():
        return
    try:
        sync_crm_to_google_sheets(store)
        log.info("CRM → Google Sheets: синхронизация выполнена.")
    except Exception as e:
        log.warning("CRM → Google Sheets: сбой синхронизации: %s", e, exc_info=True)
