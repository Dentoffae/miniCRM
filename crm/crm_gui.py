"""
Десктопный клиент мини-CRM (Tkinter): все операции через HTTP к локальному FastAPI.

Сначала запустите API: из корня проекта — python crm/crm.py
Затем: python crm/crm_gui.py

Переменные окружения (в корневом .env или в системе):
  CRM_API_BASE_URL — явный URL API (если не задан, перебираются 8000 и 8080)

Локальный бэкенд: python crm/crm.py (порт 8000).
Docker Compose из корня проекта обычно публикует API на порту 8080.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import webbrowser
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import urlencode

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SETTINGS_BASE = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from google_report_export import export_to_google_sheet  # noqa: E402
from google_report_settings import (  # noqa: E402
    load_settings,
    save_settings,
    validate_oauth_client_json_path,
    validate_token_json_path,
)
try:
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass


def _probe_health(base_url: str, timeout: float = 2.0) -> bool:
    base_url = base_url.rstrip("/")
    try:
        req = urllib.request.Request(f"{base_url}/health", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError):
        return False


def _discover_api_url() -> tuple[str, bool]:
    """Подбор рабочего URL: сначала CRM_API_BASE_URL из .env, затем :8000 и :8080 (Docker)."""
    seen: set[str] = set()
    candidates: list[str] = []
    for raw in (
        os.environ.get("CRM_API_BASE_URL", "").strip(),
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8080",
    ):
        if not raw:
            continue
        u = raw.rstrip("/")
        if u in seen:
            continue
        seen.add(u)
        candidates.append(u)
    if not candidates:
        candidates = ["http://127.0.0.1:8000"]
    for u in candidates:
        if _probe_health(u):
            return u, True
    return candidates[0], False


DEFAULT_BASE, _ = _discover_api_url()


class CrmApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


class CrmApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def _url(self, path: str, params: Optional[dict[str, Any]] = None) -> str:
        url = f"{self.base_url}{path}"
        if params:
            q = {k: v for k, v in params.items() if v is not None and v != ""}
            if q:
                url += "?" + urlencode(q, doseq=True, safe="/")
        return url

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: Optional[dict[str, Any]] = None,
    ) -> Any:
        url = self._url(path, params)
        data: Optional[bytes] = None
        headers: dict[str, str] = {}
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 204:
                    return None
                raw = resp.read().decode("utf-8")
                if not raw.strip():
                    return None
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            msg = body
            try:
                parsed = json.loads(body)
                if isinstance(parsed, dict) and "detail" in parsed:
                    d = parsed["detail"]
                    msg = json.dumps(d, ensure_ascii=False) if not isinstance(d, str) else d
            except json.JSONDecodeError:
                pass
            raise CrmApiError(e.code, msg or str(e.reason)) from e
        except urllib.error.URLError as e:
            raise CrmApiError(0, f"Нет соединения с сервером: {e.reason}") from e

    def health(self) -> dict[str, Any]:
        return self.request("GET", "/health") or {}

    # Clients
    def clients_list(
        self,
        status: Optional[str] = None,
        q: Optional[str] = None,
        *,
        limit: int = 50000,
        offset: int = 0,
    ) -> list:
        return (
            self.request(
                "GET",
                "/clients",
                params={"status": status or None, "q": q or None, "limit": limit, "offset": offset},
            )
            or []
        )

    def client_get(self, cid: int) -> dict:
        return self.request("GET", f"/clients/{cid}")

    def client_create(self, payload: dict) -> dict:
        return self.request("POST", "/clients", json_body=payload)

    def client_update(self, cid: int, payload: dict) -> dict:
        return self.request("PATCH", f"/clients/{cid}", json_body=payload)

    def client_delete(self, cid: int) -> None:
        self.request("DELETE", f"/clients/{cid}")

    def client_archive(self, cid: int) -> dict:
        return self.request("POST", f"/clients/{cid}/archive")

    # Deals
    def deals_list(
        self,
        client_id: Optional[int] = None,
        status: Optional[str] = None,
        q: Optional[str] = None,
        *,
        limit: int = 50000,
        offset: int = 0,
    ) -> list:
        return (
            self.request(
                "GET",
                "/deals",
                params={
                    "client_id": client_id,
                    "status": status or None,
                    "q": q or None,
                    "limit": limit,
                    "offset": offset,
                },
            )
            or []
        )

    def deal_get(self, did: int) -> dict:
        return self.request("GET", f"/deals/{did}")

    def deal_create(self, payload: dict) -> dict:
        return self.request("POST", "/deals", json_body=payload)

    def deal_update(self, did: int, payload: dict) -> dict:
        return self.request("PATCH", f"/deals/{did}", json_body=payload)

    def deal_delete(self, did: int) -> None:
        self.request("DELETE", f"/deals/{did}")

    # Tasks
    def tasks_list(
        self,
        client_id: Optional[int] = None,
        deal_id: Optional[int] = None,
        completed: Optional[bool] = None,
        *,
        limit: int = 50000,
        offset: int = 0,
    ) -> list:
        p: dict[str, Any] = {"limit": limit, "offset": offset}
        if client_id is not None:
            p["client_id"] = client_id
        if deal_id is not None:
            p["deal_id"] = deal_id
        if completed is not None:
            p["completed"] = str(completed).lower()
        return self.request("GET", "/tasks", params=p) or []

    def task_get(self, tid: int) -> dict:
        return self.request("GET", f"/tasks/{tid}")

    def task_create(self, payload: dict) -> dict:
        return self.request("POST", "/tasks", json_body=payload)

    def task_update(self, tid: int, payload: dict) -> dict:
        return self.request("PATCH", f"/tasks/{tid}", json_body=payload)

    def task_delete(self, tid: int) -> None:
        self.request("DELETE", f"/tasks/{tid}")

    def sync_google(self) -> dict[str, Any]:
        return self.request("POST", "/sync/google") or {}


def _entry_row(parent: tk.Widget, row: int, label: str, width: int = 40) -> ttk.Entry:
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=4, pady=2)
    e = ttk.Entry(parent, width=width)
    e.grid(row=row, column=1, sticky="ew", padx=4, pady=2)
    return e


def _text_row(parent: tk.Widget, row: int, label: str, height: int = 4) -> tk.Text:
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="nw", padx=4, pady=2)
    t = tk.Text(parent, width=50, height=height, wrap="word")
    t.grid(row=row, column=1, sticky="nsew", padx=4, pady=2)
    return t


class CrmGuiApp:
    def __init__(self) -> None:
        self.api = CrmApiClient(DEFAULT_BASE)
        self.root = tk.Tk()
        self.root.title("Мини-CRM")
        self.root.minsize(900, 520)
        self._setup_style()

        top = ttk.Frame(self.root, padding=6)
        top.pack(fill="x")
        ttk.Label(top, text="API:").pack(side="left")
        self.base_var = tk.StringVar(value=DEFAULT_BASE)
        ttk.Entry(top, textvariable=self.base_var, width=45).pack(side="left", padx=4)
        ttk.Button(top, text="Проверить", command=self._check_health).pack(side="left", padx=4)
        ttk.Button(top, text="→ Google Sheets", command=self._sync_google).pack(side="left", padx=8)
        ttk.Button(top, text="Настройки Google (отчёты)", command=self._open_google_settings).pack(
            side="left", padx=8
        )

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        self._clients_tab(nb)
        self._deals_tab(nb)
        self._tasks_tab(nb)

        self.root.after(200, self._check_health_silent)

    def _setup_style(self) -> None:
        style = ttk.Style()
        if sys.platform == "win32":
            try:
                style.theme_use("vista")
            except tk.TclError:
                pass

    def _check_health(self) -> None:
        try:
            self.api = CrmApiClient(self.base_var.get().strip())
            h = self.api.health()
            messagebox.showinfo("Сервер", f"Ок: {h}")
        except CrmApiError as e:
            messagebox.showerror("Ошибка", str(e))

    def _sync_google(self) -> None:
        try:
            self.api = CrmApiClient(self.base_var.get().strip())
            r = self.api.sync_google()
            messagebox.showinfo("Google Sheets", f"Готово.\n{r}")
        except CrmApiError as e:
            messagebox.showerror("Google Sheets", str(e))

    def _paste_into(self, entry: ttk.Entry) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            return
        entry.delete(0, tk.END)
        entry.insert(0, str(text).strip())

    def _show_google_report_success(self, result: dict[str, Any]) -> None:
        """Окно с названием таблицы, ссылкой и кнопкой открытия в браузере (без сырого ID)."""
        title_doc = (result.get("title") or "Таблица").strip()
        sid = (result.get("spreadsheet_id") or "").strip()
        link = (result.get("webViewLink") or "").strip()
        if not link and sid:
            link = f"https://docs.google.com/spreadsheets/d/{sid}/edit"

        win = tk.Toplevel(self.root)
        win.title("Отчёт Google")
        win.transient(self.root)
        win.grab_set()
        f = ttk.Frame(win, padding=14)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="Таблица успешно создана.", font=("", 10, "bold")).pack(anchor="w")
        ttk.Label(f, text=title_doc, wraplength=520).pack(anchor="w", pady=(4, 10))

        if link:
            ttk.Label(f, text="Ссылка (можно скопировать):").pack(anchor="w")
            row = ttk.Frame(f)
            row.pack(fill="x", pady=(2, 8))
            ent = tk.Entry(row, width=72)
            ent.pack(side="left", fill="x", expand=True)
            ent.insert(0, link)
            ent.config(state="readonly")

            def open_link() -> None:
                webbrowser.open(link, new=2)

            bf = ttk.Frame(f)
            bf.pack(fill="x", pady=(0, 6))
            ttk.Button(bf, text="Открыть в браузере", command=open_link).pack(side="left", padx=(0, 8))
        else:
            ttk.Label(
                f,
                text="Ссылка недоступна. Проверьте права Drive/Sheets.",
                foreground="gray",
            ).pack(anchor="w", pady=(0, 8))

        ttk.Button(f, text="Закрыть", command=win.destroy).pack(anchor="e")

    def _open_google_settings(self) -> None:
        s = load_settings(_SETTINGS_BASE)
        default_token = str(_SETTINGS_BASE / "google_oauth_token.json")
        win = tk.Toplevel(self.root)
        win.title("Настройки Google (отчёты OAuth)")
        win.transient(self.root)
        win.grab_set()
        f = ttk.Frame(win, padding=12)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        v_client = tk.StringVar(value=s.get("oauth_client_json") or "")
        v_token = tk.StringVar(value=s.get("oauth_token_json") or default_token)
        v_folder = tk.StringVar(value=s.get("drive_folder_id") or "")

        def row_browse(row: int, var: tk.StringVar, title: str) -> None:
            ttk.Label(f, text="OAuth client JSON").grid(row=row, column=0, sticky="nw", padx=4, pady=4)
            fr = ttk.Frame(f)
            fr.grid(row=row, column=1, sticky="ew", padx=4, pady=4)
            fr.columnconfigure(0, weight=1)
            e = ttk.Entry(fr, textvariable=var, width=56)
            e.grid(row=0, column=0, sticky="ew")

            def browse() -> None:
                p = filedialog.askopenfilename(
                    title=title,
                    filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")],
                )
                if p:
                    var.set(p)

            ttk.Button(fr, text="Обзор…", command=browse).grid(row=0, column=1, padx=4)

        row_browse(0, v_client, "Файл client_secret / OAuth client JSON")
        row_browse(1, v_token, "Файл token.json (отдельный файл; создаётся при первом входе, не client_secret)")

        ttk.Label(f, text="ID папки Drive").grid(row=2, column=0, sticky="nw", padx=4, pady=4)
        fr2 = ttk.Frame(f)
        fr2.grid(row=2, column=1, sticky="ew", padx=4, pady=4)
        fr2.columnconfigure(0, weight=1)
        e_folder = ttk.Entry(fr2, textvariable=v_folder, width=50)
        e_folder.grid(row=0, column=0, sticky="ew")
        ttk.Button(fr2, text="Вставить", command=lambda: self._paste_into(e_folder)).grid(
            row=0, column=1, padx=4
        )

        ttk.Label(
            f,
            text="Первое поле — только client_secret_….json (тип Desktop).\n"
            "Второе — путь к token.json (его ещё нет — оставьте путь по умолчанию; не указывайте client_secret).\n"
            "Пути сохраняются в google_report_settings.json. При первом входе откроется браузер.",
            justify="left",
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=4, pady=8)

        bf = ttk.Frame(f)
        bf.grid(row=4, column=0, columnspan=2, pady=10)

        def ok() -> None:
            save_settings(
                _SETTINGS_BASE,
                {
                    "oauth_client_json": v_client.get().strip(),
                    "oauth_token_json": v_token.get().strip() or default_token,
                    "drive_folder_id": v_folder.get().strip(),
                },
            )
            win.destroy()

        ttk.Button(bf, text="Сохранить", command=ok).pack(side="left", padx=4)
        ttk.Button(bf, text="Отмена", command=win.destroy).pack(side="left", padx=4)

    def _export_report_run(self, kind: Literal["clients", "deals", "tasks"]) -> None:
        s = load_settings(_SETTINGS_BASE)
        if not s.get("oauth_client_json") or not s.get("drive_folder_id"):
            messagebox.showwarning(
                "Отчёт",
                "Укажите в «Настройки Google (отчёты)» JSON клиента и ID папки Drive.",
            )
            return
        token_path = s.get("oauth_token_json") or str(_SETTINGS_BASE / "google_oauth_token.json")

        err = validate_oauth_client_json_path(s["oauth_client_json"])
        if err:
            messagebox.showerror("Отчёт Google", err)
            return
        err = validate_token_json_path(token_path)
        if err:
            messagebox.showerror("Отчёт Google", err)
            return

        # OAuth (браузер, run_local_server) должен выполняться в главном потоке Tkinter, не в worker.
        try:
            from google_integration.google_drive import GoogleDriveOAuthClient

            drive = GoogleDriveOAuthClient(
                client_secrets_path=s["oauth_client_json"].strip(),
                token_path=token_path.strip(),
            )
        except Exception as e:
            messagebox.showerror(
                "Отчёт Google",
                str(e)
                + "\n\nЕсли менялись права (Sheets/Drive), удалите token.json и войдите снова.",
            )
            return

        self.root.config(cursor="watch")
        self.root.update_idletasks()

        def work(drive_client: object) -> None:
            try:
                api = CrmApiClient(self.base_var.get().strip())
                if kind == "clients":
                    records = api.clients_list(limit=50_000)
                elif kind == "deals":
                    records = api.deals_list(limit=50_000)
                else:
                    records = api.tasks_list(limit=50_000)
                result = export_to_google_sheet(
                    kind=kind,
                    records=records,
                    folder_id=s["drive_folder_id"],
                    drive_client=drive_client,
                )
                self.root.after(0, lambda r=result: self._show_google_report_success(r))
            except Exception as e:
                self.root.after(0, lambda err=e: messagebox.showerror("Отчёт Google", str(err)))
            finally:
                self.root.after(0, lambda: self.root.config(cursor=""))

        threading.Thread(target=work, args=(drive,), daemon=True).start()

    def _export_report_clients(self) -> None:
        self._export_report_run("clients")

    def _export_report_deals(self) -> None:
        self._export_report_run("deals")

    def _export_report_tasks(self) -> None:
        self._export_report_run("tasks")

    def _check_health_silent(self) -> None:
        url = self.base_var.get().strip()
        try:
            self.api = CrmApiClient(url)
            self.api.health()
            return
        except CrmApiError:
            pass
        found, ok = _discover_api_url()
        if ok and found != url:
            self.base_var.set(found)
            try:
                self.api = CrmApiClient(found)
                self.api.health()
                return
            except CrmApiError:
                pass
        current = self.base_var.get().strip()
        messagebox.showwarning(
            "Мини-CRM",
            "Не удалось связаться с API.\n\n"
            f"Сейчас в поле «API»: {current}\n\n"
            "Запустите бэкенд:\n"
            "  • Локально:  python crm/crm.py  (порт 8000)\n"
            "  • Docker:    docker compose up -d  (часто порт 8080)\n\n"
            "Поменяйте URL в поле «API» и нажмите «Проверить».",
        )

    def _tree_frame(self, parent: ttk.Widget) -> tuple[ttk.Frame, ttk.Treeview, dict[str, tk.Scrollbar]]:
        frm = ttk.Frame(parent)
        frm.pack(fill="both", expand=True)
        frm.rowconfigure(0, weight=1)
        frm.columnconfigure(0, weight=1)
        tree = ttk.Treeview(frm, show="headings", selectmode="browse")
        vsb = ttk.Scrollbar(frm, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(frm, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        return frm, tree, {"vsb": vsb, "hsb": hsb}

    def _selected_id(self, tree: ttk.Treeview) -> Optional[int]:
        sel = tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except ValueError:
            return None

    # --- Clients ---
    def _clients_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=4)
        nb.add(tab, text="Клиенты")
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 4))
        self.client_search = tk.StringVar()
        ttk.Entry(bar, textvariable=self.client_search, width=28).pack(side="left", padx=2)
        ttk.Button(bar, text="Поиск", command=self._clients_refresh).pack(side="left", padx=2)
        ttk.Button(bar, text="Обновить", command=self._clients_refresh).pack(side="left", padx=2)
        ttk.Button(bar, text="Добавить", command=self._client_add).pack(side="left", padx=2)
        ttk.Button(bar, text="Изменить", command=self._client_edit).pack(side="left", padx=2)
        ttk.Button(bar, text="Архив", command=self._client_archive).pack(side="left", padx=2)
        ttk.Button(bar, text="Удалить", command=self._client_delete).pack(side="left", padx=2)
        ttk.Button(bar, text="Выгрузить отчёт", command=self._export_report_clients).pack(
            side="right", padx=8
        )
        _, self.tree_clients, _ = self._tree_frame(tab)
        cols = ("id", "name", "email", "phone", "company", "status", "updated_at")
        self.tree_clients["columns"] = cols
        for c in cols:
            self.tree_clients.heading(c, text=c)
            self.tree_clients.column(c, width=100 if c != "name" else 160, stretch=True)
        self.tree_clients.column("id", width=44, stretch=False)

    def _clients_refresh(self) -> None:
        try:
            self.api = CrmApiClient(self.base_var.get().strip())
            q = self.client_search.get().strip() or None
            rows = self.api.clients_list(q=q)
        except CrmApiError as e:
            messagebox.showerror("Клиенты", str(e))
            return
        self.tree_clients.delete(*self.tree_clients.get_children())
        for r in rows:
            self.tree_clients.insert(
                "",
                "end",
                iid=str(r["id"]),
                values=(
                    r["id"],
                    r.get("name") or "",
                    r.get("email") or "",
                    r.get("phone") or "",
                    r.get("company") or "",
                    r.get("status") or "",
                    r.get("updated_at") or "",
                ),
            )

    def _client_dialog(self, title: str, initial: Optional[dict] = None) -> Optional[dict]:
        initial = initial or {}
        win = tk.Toplevel(self.root)
        win.title(title)
        win.transient(self.root)
        win.grab_set()
        f = ttk.Frame(win, padding=10)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        e_name = _entry_row(f, 0, "Имя *")
        e_name.insert(0, initial.get("name") or "")
        e_email = _entry_row(f, 1, "Email")
        e_email.insert(0, initial.get("email") or "")
        e_phone = _entry_row(f, 2, "Телефон")
        e_phone.insert(0, initial.get("phone") or "")
        e_company = _entry_row(f, 3, "Компания")
        e_company.insert(0, initial.get("company") or "")
        t_notes = _text_row(f, 4, "Заметки")
        t_notes.insert("1.0", initial.get("notes") or "")
        ttk.Label(f, text="Статус").grid(row=5, column=0, sticky="w", padx=4, pady=2)
        cb_status = ttk.Combobox(
            f,
            values=("active", "archived"),
            width=37,
            state="readonly",
        )
        cb_status.set(initial.get("status") or "active")
        cb_status.grid(row=5, column=1, sticky="w", padx=4, pady=2)
        result: list[Optional[dict]] = [None]

        def ok() -> None:
            name = e_name.get().strip()
            if not name:
                messagebox.showwarning("Клиент", "Укажите имя.")
                return
            result[0] = {
                "name": name,
                "email": e_email.get().strip() or None,
                "phone": e_phone.get().strip() or None,
                "company": e_company.get().strip() or None,
                "notes": t_notes.get("1.0", "end").strip() or None,
                "status": cb_status.get(),
            }
            win.destroy()

        def cancel() -> None:
            win.destroy()

        bf = ttk.Frame(f)
        bf.grid(row=6, column=0, columnspan=2, pady=10)
        ttk.Button(bf, text="OK", command=ok).pack(side="left", padx=4)
        ttk.Button(bf, text="Отмена", command=cancel).pack(side="left", padx=4)
        win.wait_window()
        return result[0]

    def _client_add(self) -> None:
        data = self._client_dialog("Новый клиент")
        if not data:
            return
        try:
            self.api = CrmApiClient(self.base_var.get().strip())
            self.api.client_create(data)
            self._clients_refresh()
        except CrmApiError as e:
            messagebox.showerror("Клиент", str(e))

    def _client_edit(self) -> None:
        cid = self._selected_id(self.tree_clients)
        if cid is None:
            messagebox.showinfo("Клиент", "Выберите строку.")
            return
        try:
            self.api = CrmApiClient(self.base_var.get().strip())
            cur = self.api.client_get(cid)
        except CrmApiError as e:
            messagebox.showerror("Клиент", str(e))
            return
        data = self._client_dialog("Редактировать клиента", cur)
        if not data:
            return
        try:
            self.api.client_update(cid, data)
            self._clients_refresh()
        except CrmApiError as e:
            messagebox.showerror("Клиент", str(e))

    def _client_archive(self) -> None:
        cid = self._selected_id(self.tree_clients)
        if cid is None:
            messagebox.showinfo("Клиент", "Выберите строку.")
            return
        try:
            self.api = CrmApiClient(self.base_var.get().strip())
            self.api.client_archive(cid)
            self._clients_refresh()
        except CrmApiError as e:
            messagebox.showerror("Клиент", str(e))

    def _client_delete(self) -> None:
        cid = self._selected_id(self.tree_clients)
        if cid is None:
            messagebox.showinfo("Клиент", "Выберите строку.")
            return
        if not messagebox.askyesno("Удалить", "Удалить клиента безвозвратно?"):
            return
        try:
            self.api = CrmApiClient(self.base_var.get().strip())
            self.api.client_delete(cid)
            self._clients_refresh()
        except CrmApiError as e:
            messagebox.showerror("Клиент", str(e))

    # --- Deals ---
    def _deals_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=4)
        nb.add(tab, text="Сделки")
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 4))
        self.deal_search = tk.StringVar()
        ttk.Entry(bar, textvariable=self.deal_search, width=24).pack(side="left", padx=2)
        ttk.Button(bar, text="Поиск", command=self._deals_refresh).pack(side="left", padx=2)
        ttk.Button(bar, text="Обновить", command=self._deals_refresh).pack(side="left", padx=2)
        ttk.Button(bar, text="Добавить", command=self._deal_add).pack(side="left", padx=2)
        ttk.Button(bar, text="Изменить", command=self._deal_edit).pack(side="left", padx=2)
        ttk.Button(bar, text="Удалить", command=self._deal_delete).pack(side="left", padx=2)
        ttk.Button(bar, text="Выгрузить отчёт", command=self._export_report_deals).pack(
            side="right", padx=8
        )
        _, self.tree_deals, _ = self._tree_frame(tab)
        cols = ("id", "title", "client_id", "status", "amount", "currency", "order_number", "updated_at")
        self.tree_deals["columns"] = cols
        for c in cols:
            self.tree_deals.heading(c, text=c)
            self.tree_deals.column(c, width=90, stretch=True)
        self.tree_deals.column("id", width=44, stretch=False)
        self.tree_deals.column("title", width=180, stretch=True)

    def _deals_refresh(self) -> None:
        try:
            self.api = CrmApiClient(self.base_var.get().strip())
            q = self.deal_search.get().strip() or None
            rows = self.api.deals_list(q=q)
        except CrmApiError as e:
            messagebox.showerror("Сделки", str(e))
            return
        self.tree_deals.delete(*self.tree_deals.get_children())
        for r in rows:
            amt = r.get("amount")
            amt_s = "" if amt is None else str(amt)
            self.tree_deals.insert(
                "",
                "end",
                iid=str(r["id"]),
                values=(
                    r["id"],
                    r.get("title") or "",
                    r.get("client_id") if r.get("client_id") is not None else "",
                    r.get("status") or "",
                    amt_s,
                    r.get("currency") or "",
                    r.get("order_number") or "",
                    r.get("updated_at") or "",
                ),
            )

    def _deal_dialog(self, title: str, initial: Optional[dict] = None) -> Optional[dict]:
        initial = initial or {}
        win = tk.Toplevel(self.root)
        win.title(title)
        win.transient(self.root)
        win.grab_set()
        f = ttk.Frame(win, padding=10)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        e_title = _entry_row(f, 0, "Название *")
        e_title.insert(0, initial.get("title") or "")
        e_cid = _entry_row(f, 1, "ID клиента (пусто = нет)")
        v = initial.get("client_id")
        e_cid.insert(0, "" if v is None else str(v))
        t_desc = _text_row(f, 2, "Описание", height=3)
        t_desc.insert("1.0", initial.get("description") or "")
        e_amount = _entry_row(f, 3, "Сумма")
        if initial.get("amount") is not None:
            e_amount.insert(0, str(initial["amount"]))
        e_cur = _entry_row(f, 4, "Валюта")
        e_cur.insert(0, initial.get("currency") or "RUB")
        e_status = _entry_row(f, 5, "Статус")
        e_status.insert(0, initial.get("status") or "lead")
        e_ord = _entry_row(f, 6, "Номер заказа")
        e_ord.insert(0, initial.get("order_number") or "")
        result: list[Optional[dict]] = [None]

        def ok() -> None:
            t = e_title.get().strip()
            if not t:
                messagebox.showwarning("Сделка", "Укажите название.")
                return
            cid_raw = e_cid.get().strip()
            client_id: Optional[int]
            if not cid_raw:
                client_id = None
            else:
                try:
                    client_id = int(cid_raw)
                except ValueError:
                    messagebox.showwarning("Сделка", "ID клиента должен быть числом.")
                    return
            amt_raw = e_amount.get().strip()
            amount: Optional[float]
            if not amt_raw:
                amount = None
            else:
                try:
                    amount = float(amt_raw.replace(",", "."))
                except ValueError:
                    messagebox.showwarning("Сделка", "Сумма должна быть числом.")
                    return
            result[0] = {
                "client_id": client_id,
                "title": t,
                "description": t_desc.get("1.0", "end").strip() or None,
                "amount": amount,
                "currency": e_cur.get().strip() or "RUB",
                "status": e_status.get().strip() or "lead",
                "order_number": e_ord.get().strip() or None,
            }
            win.destroy()

        def cancel() -> None:
            win.destroy()

        bf = ttk.Frame(f)
        bf.grid(row=7, column=0, columnspan=2, pady=10)
        ttk.Button(bf, text="OK", command=ok).pack(side="left", padx=4)
        ttk.Button(bf, text="Отмена", command=cancel).pack(side="left", padx=4)
        win.wait_window()
        return result[0]

    def _deal_add(self) -> None:
        data = self._deal_dialog("Новая сделка")
        if not data:
            return
        try:
            self.api = CrmApiClient(self.base_var.get().strip())
            self.api.deal_create(data)
            self._deals_refresh()
        except CrmApiError as e:
            messagebox.showerror("Сделка", str(e))

    def _deal_edit(self) -> None:
        did = self._selected_id(self.tree_deals)
        if did is None:
            messagebox.showinfo("Сделка", "Выберите строку.")
            return
        try:
            self.api = CrmApiClient(self.base_var.get().strip())
            cur = self.api.deal_get(did)
        except CrmApiError as e:
            messagebox.showerror("Сделка", str(e))
            return
        data = self._deal_dialog("Редактировать сделку", cur)
        if not data:
            return
        try:
            self.api.deal_update(did, data)
            self._deals_refresh()
        except CrmApiError as e:
            messagebox.showerror("Сделка", str(e))

    def _deal_delete(self) -> None:
        did = self._selected_id(self.tree_deals)
        if did is None:
            messagebox.showinfo("Сделка", "Выберите строку.")
            return
        if not messagebox.askyesno("Удалить", "Удалить сделку?"):
            return
        try:
            self.api = CrmApiClient(self.base_var.get().strip())
            self.api.deal_delete(did)
            self._deals_refresh()
        except CrmApiError as e:
            messagebox.showerror("Сделка", str(e))

    # --- Tasks ---
    def _tasks_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=4)
        nb.add(tab, text="Задачи")
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 4))
        ttk.Button(bar, text="Обновить", command=self._tasks_refresh).pack(side="left", padx=2)
        ttk.Button(bar, text="Добавить", command=self._task_add).pack(side="left", padx=2)
        ttk.Button(bar, text="Изменить", command=self._task_edit).pack(side="left", padx=2)
        ttk.Button(bar, text="Выполнено", command=lambda: self._task_toggle_done(True)).pack(
            side="left", padx=2
        )
        ttk.Button(bar, text="Не выполнено", command=lambda: self._task_toggle_done(False)).pack(
            side="left", padx=2
        )
        ttk.Button(bar, text="Удалить", command=self._task_delete).pack(side="left", padx=2)
        ttk.Button(bar, text="Выгрузить отчёт", command=self._export_report_tasks).pack(
            side="right", padx=8
        )
        _, self.tree_tasks, _ = self._tree_frame(tab)
        cols = ("id", "title", "client_id", "deal_id", "completed", "due_at", "updated_at")
        self.tree_tasks["columns"] = cols
        for c in cols:
            self.tree_tasks.heading(c, text=c)
            self.tree_tasks.column(c, width=85, stretch=True)
        self.tree_tasks.column("id", width=44, stretch=False)
        self.tree_tasks.column("title", width=200, stretch=True)

    def _tasks_refresh(self) -> None:
        try:
            self.api = CrmApiClient(self.base_var.get().strip())
            rows = self.api.tasks_list()
        except CrmApiError as e:
            messagebox.showerror("Задачи", str(e))
            return
        self.tree_tasks.delete(*self.tree_tasks.get_children())
        for r in rows:
            self.tree_tasks.insert(
                "",
                "end",
                iid=str(r["id"]),
                values=(
                    r["id"],
                    r.get("title") or "",
                    r.get("client_id") if r.get("client_id") is not None else "",
                    r.get("deal_id") if r.get("deal_id") is not None else "",
                    "да" if r.get("completed") else "нет",
                    r.get("due_at") or "",
                    r.get("updated_at") or "",
                ),
            )

    def _task_dialog(self, title: str, initial: Optional[dict] = None) -> Optional[dict]:
        initial = initial or {}
        win = tk.Toplevel(self.root)
        win.title(title)
        win.transient(self.root)
        win.grab_set()
        f = ttk.Frame(win, padding=10)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        e_title = _entry_row(f, 0, "Заголовок *")
        e_title.insert(0, initial.get("title") or "")
        e_cid = _entry_row(f, 1, "ID клиента")
        v = initial.get("client_id")
        e_cid.insert(0, "" if v is None else str(v))
        e_did = _entry_row(f, 2, "ID сделки")
        v2 = initial.get("deal_id")
        e_did.insert(0, "" if v2 is None else str(v2))
        e_due = _entry_row(f, 3, "Срок (ISO, напр. 2026-04-10T12:00:00+00:00)")
        e_due.insert(0, initial.get("due_at") or "")
        t_desc = _text_row(f, 4, "Описание", height=3)
        t_desc.insert("1.0", initial.get("description") or "")
        ttk.Label(f, text="Выполнена").grid(row=5, column=0, sticky="w", padx=4, pady=2)
        done_var = tk.BooleanVar(value=bool(initial.get("completed")))
        ttk.Checkbutton(f, variable=done_var).grid(row=5, column=1, sticky="w", padx=4, pady=2)
        result: list[Optional[dict]] = [None]

        def parse_opt_int(entry: ttk.Entry) -> Optional[int]:
            s = entry.get().strip()
            if not s:
                return None
            return int(s)

        def ok() -> None:
            t = e_title.get().strip()
            if not t:
                messagebox.showwarning("Задача", "Укажите заголовок.")
                return
            try:
                cid = parse_opt_int(e_cid)
                did = parse_opt_int(e_did)
            except ValueError:
                messagebox.showwarning("Задача", "ID должны быть целыми числами.")
                return
            result[0] = {
                "title": t,
                "client_id": cid,
                "deal_id": did,
                "due_at": e_due.get().strip() or None,
                "description": t_desc.get("1.0", "end").strip() or None,
                "completed": done_var.get(),
            }
            win.destroy()

        def cancel() -> None:
            win.destroy()

        bf = ttk.Frame(f)
        bf.grid(row=6, column=0, columnspan=2, pady=10)
        ttk.Button(bf, text="OK", command=ok).pack(side="left", padx=4)
        ttk.Button(bf, text="Отмена", command=cancel).pack(side="left", padx=4)
        win.wait_window()
        return result[0]

    def _task_add(self) -> None:
        data = self._task_dialog("Новая задача")
        if not data:
            return
        try:
            self.api = CrmApiClient(self.base_var.get().strip())
            self.api.task_create(data)
            self._tasks_refresh()
        except CrmApiError as e:
            messagebox.showerror("Задача", str(e))

    def _task_edit(self) -> None:
        tid = self._selected_id(self.tree_tasks)
        if tid is None:
            messagebox.showinfo("Задача", "Выберите строку.")
            return
        try:
            self.api = CrmApiClient(self.base_var.get().strip())
            cur = self.api.task_get(tid)
        except CrmApiError as e:
            messagebox.showerror("Задача", str(e))
            return
        data = self._task_dialog("Редактировать задачу", cur)
        if not data:
            return
        try:
            self.api.task_update(tid, data)
            self._tasks_refresh()
        except CrmApiError as e:
            messagebox.showerror("Задача", str(e))

    def _task_toggle_done(self, done: bool) -> None:
        tid = self._selected_id(self.tree_tasks)
        if tid is None:
            messagebox.showinfo("Задача", "Выберите строку.")
            return
        try:
            self.api = CrmApiClient(self.base_var.get().strip())
            self.api.task_update(tid, {"completed": done})
            self._tasks_refresh()
        except CrmApiError as e:
            messagebox.showerror("Задача", str(e))

    def _task_delete(self) -> None:
        tid = self._selected_id(self.tree_tasks)
        if tid is None:
            messagebox.showinfo("Задача", "Выберите строку.")
            return
        if not messagebox.askyesno("Удалить", "Удалить задачу?"):
            return
        try:
            self.api = CrmApiClient(self.base_var.get().strip())
            self.api.task_delete(tid)
            self._tasks_refresh()
        except CrmApiError as e:
            messagebox.showerror("Задача", str(e))

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass
    CrmGuiApp().run()


if __name__ == "__main__":
    main()
