"""
FastAPI backend для мини-CRM. Endpoints для клиентов, сделок и задач.
"""

from __future__ import annotations

from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

import os
import sqlite3
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from crm_database import CRMStore, Client, Deal, InteractionTask
from crm_google_sync import sync_crm_to_google_after_write, sync_crm_to_google_sheets

DEFAULT_DB = os.environ.get("CRM_DB_PATH", "crm.sqlite3")


def _push_google(store: CRMStore) -> None:
    """После любой мутации данных — снимок в Google Таблицу (если настроено в .env)."""
    sync_crm_to_google_after_write(store)


def _require_client_exists(store: CRMStore, client_id: Optional[int]) -> None:
    if client_id is None:
        return
    if store.client_get(client_id) is None:
        raise HTTPException(
            status_code=400,
            detail=f"Клиент с id={client_id} не найден. Оставьте «ID клиента» пустым или укажите существующий id из вкладки «Клиенты».",
        )


def _require_deal_exists(store: CRMStore, deal_id: Optional[int]) -> None:
    if deal_id is None:
        return
    if store.deal_get(deal_id) is None:
        raise HTTPException(
            status_code=400,
            detail=f"Сделка с id={deal_id} не найдена. Оставьте «ID сделки» пустым или укажите существующий id из вкладки «Сделки».",
        )


_FK_HINT = "Проверьте id клиента и сделки или оставьте поля пустыми."


def get_store() -> CRMStore:
    return CRMStore(DEFAULT_DB)


app = FastAPI(title="Mini CRM API", version="0.1.0")


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    """Для несуществующего пути — подсказка URL; для своих 404 (клиент не найден и т.д.) — как раньше."""
    if isinstance(exc, HTTPException) and exc.status_code == 404:
        d = exc.detail
        if d != "Not Found":
            return JSONResponse(status_code=404, content={"detail": d})
    base = str(request.base_url).rstrip("/")
    return JSONResponse(
        status_code=404,
        content={
            "detail": "Not Found",
            "path": request.url.path,
            "hints": {
                "home_html": f"{base}/",
                "swagger_ui": f"{base}/docs",
                "openapi_json": f"{base}/openapi.json",
                "health": f"{base}/health",
                "clients": f"{base}/clients",
            },
        },
    )


# --- Pydantic схемы ---


class ClientCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None
    status: str = "active"


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None


class ClientOut(BaseModel):
    id: int
    name: str
    email: Optional[str]
    phone: Optional[str]
    company: Optional[str]
    notes: Optional[str]
    status: str
    created_at: str
    updated_at: str


class DealCreate(BaseModel):
    client_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    amount: Optional[float] = None
    currency: str = "RUB"
    status: str = "lead"
    order_number: Optional[str] = None


class DealUpdate(BaseModel):
    client_id: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    status: Optional[str] = None
    order_number: Optional[str] = None


class DealOut(BaseModel):
    id: int
    client_id: Optional[int]
    title: str
    description: Optional[str]
    amount: Optional[float]
    currency: str
    status: str
    order_number: Optional[str]
    created_at: str
    updated_at: str


class TaskCreate(BaseModel):
    client_id: Optional[int] = None
    deal_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    due_at: Optional[str] = None
    completed: bool = False


class TaskUpdate(BaseModel):
    client_id: Optional[int] = None
    deal_id: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    due_at: Optional[str] = None
    completed: Optional[bool] = None


class TaskOut(BaseModel):
    id: int
    client_id: Optional[int]
    deal_id: Optional[int]
    title: str
    description: Optional[str]
    due_at: Optional[str]
    completed: bool
    created_at: str
    updated_at: str


def _client_out(c: Client) -> ClientOut:
    return ClientOut(
        id=c.id,  # type: ignore[arg-type]
        name=c.name,
        email=c.email,
        phone=c.phone,
        company=c.company,
        notes=c.notes,
        status=c.status,
        created_at=c.created_at or "",
        updated_at=c.updated_at or "",
    )


def _deal_out(d: Deal) -> DealOut:
    return DealOut(
        id=d.id,  # type: ignore[arg-type]
        client_id=d.client_id,
        title=d.title,
        description=d.description,
        amount=d.amount,
        currency=d.currency,
        status=d.status,
        order_number=d.order_number,
        created_at=d.created_at or "",
        updated_at=d.updated_at or "",
    )


def _task_out(t: InteractionTask) -> TaskOut:
    return TaskOut(
        id=t.id,  # type: ignore[arg-type]
        client_id=t.client_id,
        deal_id=t.deal_id,
        title=t.title,
        description=t.description,
        due_at=t.due_at,
        completed=t.completed,
        created_at=t.created_at or "",
        updated_at=t.updated_at or "",
    )


# ----- Clients -----


@app.post("/clients", response_model=ClientOut)
def create_client(body: ClientCreate, store: CRMStore = Depends(get_store)) -> ClientOut:
    c = store.client_create(
        Client(
            name=body.name,
            email=body.email,
            phone=body.phone,
            company=body.company,
            notes=body.notes,
            status=body.status,
        )
    )
    _push_google(store)
    return _client_out(c)  # type: ignore[arg-type]


@app.get("/clients/{client_id}", response_model=ClientOut)
def get_client(client_id: int, store: CRMStore = Depends(get_store)) -> ClientOut:
    c = store.client_get(client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    return _client_out(c)


@app.get("/clients", response_model=list[ClientOut])
def list_clients(
    status: Optional[str] = None,
    q: Optional[str] = Query(None, description="Поиск по имени, email, телефону, компании, заметкам (без учёта регистра)"),
    limit: int = Query(200, ge=1, le=100_000),
    offset: int = Query(0, ge=0),
    store: CRMStore = Depends(get_store),
) -> list[ClientOut]:
    rows = store.client_list(status=status, search=q, limit=limit, offset=offset)
    return [_client_out(c) for c in rows]


@app.patch("/clients/{client_id}", response_model=ClientOut)
def update_client(
    client_id: int,
    body: ClientUpdate,
    store: CRMStore = Depends(get_store),
) -> ClientOut:
    data = body.model_dump(exclude_unset=True)
    c = store.client_update(client_id, **data)
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    _push_google(store)
    return _client_out(c)


@app.delete("/clients/{client_id}", status_code=204)
def delete_client(client_id: int, store: CRMStore = Depends(get_store)) -> None:
    if not store.client_delete(client_id):
        raise HTTPException(status_code=404, detail="Client not found")
    _push_google(store)


@app.post("/clients/{client_id}/archive", response_model=ClientOut)
def archive_client(client_id: int, store: CRMStore = Depends(get_store)) -> ClientOut:
    c = store.client_archive(client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    _push_google(store)
    return _client_out(c)


# ----- Deals -----


@app.post("/deals", response_model=DealOut)
def create_deal(body: DealCreate, store: CRMStore = Depends(get_store)) -> DealOut:
    _require_client_exists(store, body.client_id)
    try:
        d = store.deal_create(
            Deal(
                client_id=body.client_id,
                title=body.title,
                description=body.description,
                amount=body.amount,
                currency=body.currency,
                status=body.status,
                order_number=body.order_number,
            )
        )
    except sqlite3.IntegrityError as e:
        raise HTTPException(status_code=400, detail=_FK_HINT) from e
    if not d:
        raise HTTPException(status_code=500, detail="Сделка не сохранилась")
    _push_google(store)
    return _deal_out(d)


@app.get("/deals/{deal_id}", response_model=DealOut)
def get_deal(deal_id: int, store: CRMStore = Depends(get_store)) -> DealOut:
    d = store.deal_get(deal_id)
    if not d:
        raise HTTPException(status_code=404, detail="Deal not found")
    return _deal_out(d)


@app.get("/deals", response_model=list[DealOut])
def list_deals(
    client_id: Optional[int] = None,
    status: Optional[str] = None,
    q: Optional[str] = Query(None, description="Поиск по названию, описанию, номеру заказа"),
    limit: int = Query(200, ge=1, le=100_000),
    offset: int = Query(0, ge=0),
    store: CRMStore = Depends(get_store),
) -> list[DealOut]:
    rows = store.deal_list(client_id=client_id, status=status, search=q, limit=limit, offset=offset)
    return [_deal_out(d) for d in rows]


@app.patch("/deals/{deal_id}", response_model=DealOut)
def update_deal(
    deal_id: int,
    body: DealUpdate,
    store: CRMStore = Depends(get_store),
) -> DealOut:
    data = body.model_dump(exclude_unset=True)
    if "client_id" in data:
        _require_client_exists(store, data["client_id"])
    try:
        d = store.deal_update(deal_id, **data)
    except sqlite3.IntegrityError as e:
        raise HTTPException(status_code=400, detail=_FK_HINT) from e
    if not d:
        raise HTTPException(status_code=404, detail="Deal not found")
    _push_google(store)
    return _deal_out(d)


@app.delete("/deals/{deal_id}", status_code=204)
def delete_deal(deal_id: int, store: CRMStore = Depends(get_store)) -> None:
    if not store.deal_delete(deal_id):
        raise HTTPException(status_code=404, detail="Deal not found")
    _push_google(store)


# ----- Tasks -----


@app.post("/tasks", response_model=TaskOut)
def create_task(body: TaskCreate, store: CRMStore = Depends(get_store)) -> TaskOut:
    _require_client_exists(store, body.client_id)
    _require_deal_exists(store, body.deal_id)
    try:
        t = store.task_create(
            InteractionTask(
                client_id=body.client_id,
                deal_id=body.deal_id,
                title=body.title,
                description=body.description,
                due_at=body.due_at,
                completed=body.completed,
            )
        )
    except sqlite3.IntegrityError as e:
        raise HTTPException(status_code=400, detail=_FK_HINT) from e
    if not t:
        raise HTTPException(status_code=500, detail="Задача не сохранилась")
    _push_google(store)
    return _task_out(t)


@app.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: int, store: CRMStore = Depends(get_store)) -> TaskOut:
    t = store.task_get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_out(t)


@app.get("/tasks", response_model=list[TaskOut])
def list_tasks(
    client_id: Optional[int] = None,
    deal_id: Optional[int] = None,
    completed: Optional[bool] = None,
    limit: int = Query(200, ge=1, le=100_000),
    offset: int = Query(0, ge=0),
    store: CRMStore = Depends(get_store),
) -> list[TaskOut]:
    rows = store.task_list(
        client_id=client_id,
        deal_id=deal_id,
        completed=completed,
        limit=limit,
        offset=offset,
    )
    return [_task_out(t) for t in rows]


@app.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(
    task_id: int,
    body: TaskUpdate,
    store: CRMStore = Depends(get_store),
) -> TaskOut:
    data = body.model_dump(exclude_unset=True)
    if "client_id" in data:
        _require_client_exists(store, data["client_id"])
    if "deal_id" in data:
        _require_deal_exists(store, data["deal_id"])
    try:
        t = store.task_update(task_id, **data)
    except sqlite3.IntegrityError as e:
        raise HTTPException(status_code=400, detail=_FK_HINT) from e
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    _push_google(store)
    return _task_out(t)


@app.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, store: CRMStore = Depends(get_store)) -> None:
    if not store.task_delete(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    _push_google(store)


@app.post("/sync/google", tags=["google"])
def sync_google_manual(store: CRMStore = Depends(get_store)) -> dict:
    """Принудительно перезаписать листы Google Таблицы снимком из CRM (нужны GOOGLE_* в окружении)."""
    try:
        return sync_crm_to_google_sheets(store)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Google API: {e}") from e


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def root() -> str:
    """Главная: ссылки на документацию (редирект иногда ломается за прокси или у клиентов без follow)."""
    return """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Mini CRM API</title>
</head>
<body>
  <h1>Mini CRM API</h1>
  <p>Рабочие адреса:</p>
  <ul>
    <li><a href="/docs">Swagger UI — <code>/docs</code></a></li>
    <li><a href="/redoc">ReDoc — <code>/redoc</code></a></li>
    <li><a href="/openapi.json">OpenAPI JSON — <code>/openapi.json</code></a></li>
    <li><a href="/health">Проверка — <code>/health</code></a></li>
    <li><a href="/clients">Список клиентов — <code>GET /clients</code></a></li>
    <li>Синхронизация с Google Sheets: <code>POST /sync/google</code> (см. <a href="/docs">/docs</a>)</li>
  </ul>
</body>
</html>"""


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
