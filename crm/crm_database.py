"""
SQLite-слой мини-CRM: модели таблиц и класс с CRUD + поиск.
Типы соответствуют SQLite: INTEGER, REAL, TEXT, BLOB (BLOB здесь не используется).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --- Модели (отражают колонки таблиц) ---


@dataclass
class Client:
    """
    Клиенты.
    SQLite: id INTEGER PK, остальное TEXT / REAL по необходимости.
    status: например 'active', 'archived'.
    """

    id: Optional[int] = None
    name: str = ""
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None
    status: str = "active"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class Deal:
    """
    Сделки / заказы. client_id может быть NULL.
    status: например 'lead', 'negotiation', 'won', 'lost', 'order_placed'.
    """

    id: Optional[int] = None
    client_id: Optional[int] = None
    title: str = ""
    description: Optional[str] = None
    amount: Optional[float] = None
    currency: str = "RUB"
    status: str = "lead"
    order_number: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class InteractionTask:
    """
    Задачи и напоминания. Связь с клиентом и/или сделкой опциональна.
    completed: в БД INTEGER 0/1.
    """

    id: Optional[int] = None
    client_id: Optional[int] = None
    deal_id: Optional[int] = None
    title: str = ""
    description: Optional[str] = None
    due_at: Optional[str] = None
    completed: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    company TEXT,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT,
    amount REAL,
    currency TEXT NOT NULL DEFAULT 'RUB',
    status TEXT NOT NULL DEFAULT 'lead',
    order_number TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_deals_client ON deals(client_id);
CREATE INDEX IF NOT EXISTS idx_deals_status ON deals(status);

CREATE TABLE IF NOT EXISTS interaction_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    deal_id INTEGER REFERENCES deals(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT,
    due_at TEXT,
    completed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_client ON interaction_tasks(client_id);
CREATE INDEX IF NOT EXISTS idx_tasks_deal ON interaction_tasks(deal_id);
CREATE INDEX IF NOT EXISTS idx_tasks_completed ON interaction_tasks(completed);
"""


def _row_to_client(r: sqlite3.Row) -> Client:
    return Client(
        id=r["id"],
        name=r["name"],
        email=r["email"],
        phone=r["phone"],
        company=r["company"],
        notes=r["notes"],
        status=r["status"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


def _row_to_deal(r: sqlite3.Row) -> Deal:
    return Deal(
        id=r["id"],
        client_id=r["client_id"],
        title=r["title"],
        description=r["description"],
        amount=r["amount"],
        currency=r["currency"],
        status=r["status"],
        order_number=r["order_number"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


def _row_to_task(r: sqlite3.Row) -> InteractionTask:
    return InteractionTask(
        id=r["id"],
        client_id=r["client_id"],
        deal_id=r["deal_id"],
        title=r["title"],
        description=r["description"],
        due_at=r["due_at"],
        completed=bool(r["completed"]),
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


class CRMStore:
    """
    Инициализация: путь к файлу БД, создание таблиц при отсутствии.
    Все операции через один класс.
    """

    def __init__(self, db_path: str | Path) -> None:
        raw = str(db_path)
        self._memory_conn: Optional[sqlite3.Connection] = None
        if raw == ":memory:":
            self.db_path = ":memory:"
            self._memory_conn = sqlite3.connect(":memory:")
            self._memory_conn.row_factory = sqlite3.Row
            self._memory_conn.execute("PRAGMA foreign_keys = ON")
        else:
            self.db_path = str(Path(raw).resolve())
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _db(self):
        # Без явного commit() при close() sqlite3 откатывает транзакцию — INSERT «пропадает»,
        # client_create возвращал None → 500 в API.
        if self._memory_conn is not None:
            try:
                yield self._memory_conn
                self._memory_conn.commit()
            except Exception:
                self._memory_conn.rollback()
                raise
            return
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._db() as conn:
            conn.executescript(SCHEMA)

    # ----- Clients -----

    def client_create(self, c: Client) -> Client:
        now = _utc_now_iso()
        with self._db() as conn:
            cur = conn.execute(
                """
                INSERT INTO clients (name, email, phone, company, notes, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    c.name,
                    c.email,
                    c.phone,
                    c.company,
                    c.notes,
                    c.status or "active",
                    now,
                    now,
                ),
            )
            cid = cur.lastrowid
        return self.client_get(cid)  # type: ignore[arg-type]

    def client_get(self, client_id: int) -> Optional[Client]:
        with self._db() as conn:
            row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
        return _row_to_client(row) if row else None

    def client_list(
        self,
        status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Client]:
        where: list[str] = []
        params: list[Any] = []
        if status is not None:
            where.append("status = ?")
            params.append(status)
        if search:
            pat = f"%{search.strip()}%"
            where.append(
                "("
                "LOWER(name) LIKE LOWER(?) OR LOWER(IFNULL(email,'')) LIKE LOWER(?) OR "
                "LOWER(IFNULL(phone,'')) LIKE LOWER(?) OR LOWER(IFNULL(company,'')) LIKE LOWER(?) OR "
                "LOWER(IFNULL(notes,'')) LIKE LOWER(?)"
                ")"
            )
            params.extend([pat, pat, pat, pat, pat])
        sql = "SELECT * FROM clients"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._db() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_client(r) for r in rows]

    def client_update(self, client_id: int, **fields: Any) -> Optional[Client]:
        allowed = {"name", "email", "phone", "company", "notes", "status"}
        updates = {k: fields[k] for k in allowed if k in fields}
        if not updates:
            return self.client_get(client_id)
        updates["updated_at"] = _utc_now_iso()
        cols = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [client_id]
        with self._db() as conn:
            conn.execute(f"UPDATE clients SET {cols} WHERE id = ?", vals)
        return self.client_get(client_id)

    def client_delete(self, client_id: int) -> bool:
        with self._db() as conn:
            cur = conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
            return cur.rowcount > 0

    def client_archive(self, client_id: int) -> Optional[Client]:
        return self.client_update(client_id, status="archived")

    # ----- Deals -----

    def deal_create(self, d: Deal) -> Deal:
        now = _utc_now_iso()
        with self._db() as conn:
            cur = conn.execute(
                """
                INSERT INTO deals (
                    client_id, title, description, amount, currency, status, order_number, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    d.client_id,
                    d.title,
                    d.description,
                    d.amount,
                    d.currency or "RUB",
                    d.status or "lead",
                    d.order_number,
                    now,
                    now,
                ),
            )
            did = cur.lastrowid
        return self.deal_get(did)  # type: ignore[arg-type]

    def deal_get(self, deal_id: int) -> Optional[Deal]:
        with self._db() as conn:
            row = conn.execute("SELECT * FROM deals WHERE id = ?", (deal_id,)).fetchone()
        return _row_to_deal(row) if row else None

    def deal_list(
        self,
        client_id: Optional[int] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Deal]:
        where: list[str] = []
        params: list[Any] = []
        if client_id is not None:
            where.append("client_id = ?")
            params.append(client_id)
        if status is not None:
            where.append("status = ?")
            params.append(status)
        if search:
            pat = f"%{search.strip()}%"
            where.append(
                "("
                "LOWER(title) LIKE LOWER(?) OR LOWER(IFNULL(description,'')) LIKE LOWER(?) OR "
                "LOWER(IFNULL(order_number,'')) LIKE LOWER(?)"
                ")"
            )
            params.extend([pat, pat, pat])
        sql = "SELECT * FROM deals"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._db() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_deal(r) for r in rows]

    def deal_update(self, deal_id: int, **fields: Any) -> Optional[Deal]:
        allowed = {
            "client_id",
            "title",
            "description",
            "amount",
            "currency",
            "status",
            "order_number",
        }
        updates = {k: fields[k] for k in allowed if k in fields}
        if not updates:
            return self.deal_get(deal_id)
        updates["updated_at"] = _utc_now_iso()
        cols = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [deal_id]
        with self._db() as conn:
            conn.execute(f"UPDATE deals SET {cols} WHERE id = ?", vals)
        return self.deal_get(deal_id)

    def deal_delete(self, deal_id: int) -> bool:
        with self._db() as conn:
            cur = conn.execute("DELETE FROM deals WHERE id = ?", (deal_id,))
            return cur.rowcount > 0

    # ----- Tasks -----

    def task_create(self, t: InteractionTask) -> InteractionTask:
        now = _utc_now_iso()
        with self._db() as conn:
            cur = conn.execute(
                """
                INSERT INTO interaction_tasks (
                    client_id, deal_id, title, description, due_at, completed, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    t.client_id,
                    t.deal_id,
                    t.title,
                    t.description,
                    t.due_at,
                    1 if t.completed else 0,
                    now,
                    now,
                ),
            )
            tid = cur.lastrowid
        return self.task_get(tid)  # type: ignore[arg-type]

    def task_get(self, task_id: int) -> Optional[InteractionTask]:
        with self._db() as conn:
            row = conn.execute(
                "SELECT * FROM interaction_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return _row_to_task(row) if row else None

    def task_list(
        self,
        client_id: Optional[int] = None,
        deal_id: Optional[int] = None,
        completed: Optional[bool] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[InteractionTask]:
        where: list[str] = []
        params: list[Any] = []
        if client_id is not None:
            where.append("client_id = ?")
            params.append(client_id)
        if deal_id is not None:
            where.append("deal_id = ?")
            params.append(deal_id)
        if completed is not None:
            where.append("completed = ?")
            params.append(1 if completed else 0)
        sql = "SELECT * FROM interaction_tasks"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY due_at IS NULL, due_at ASC, updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._db() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_task(r) for r in rows]

    def task_update(self, task_id: int, **fields: Any) -> Optional[InteractionTask]:
        allowed = {"client_id", "deal_id", "title", "description", "due_at", "completed"}
        updates: dict[str, Any] = {}
        for k in allowed:
            if k not in fields:
                continue
            v = fields[k]
            if k == "completed" and v is not None:
                updates[k] = 1 if v else 0
            else:
                updates[k] = v
        if not updates:
            return self.task_get(task_id)
        updates["updated_at"] = _utc_now_iso()
        cols = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [task_id]
        with self._db() as conn:
            conn.execute(f"UPDATE interaction_tasks SET {cols} WHERE id = ?", vals)
        return self.task_get(task_id)

    def task_delete(self, task_id: int) -> bool:
        with self._db() as conn:
            cur = conn.execute("DELETE FROM interaction_tasks WHERE id = ?", (task_id,))
            return cur.rowcount > 0
