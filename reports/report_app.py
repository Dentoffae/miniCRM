"""
Простое приложение: форма в Tkinter → симуляция данных → красивый лист в Google Таблице.
Требуются в .env: GOOGLE_SPREADSHEET_ID, GOOGLE_APPLICATION_CREDENTIALS (путь к JSON ключа).
"""

from __future__ import annotations

import os
import random
import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_google_dir = _REPO_ROOT / "google"
if _google_dir.is_dir() and str(_google_dir) not in sys.path:
    sys.path.insert(0, str(_google_dir))

import tkinter as tk
from tkinter import messagebox, ttk

from dotenv import load_dotenv
from googleapiclient.errors import HttpError

from google_sheets_crud import GoogleSheetsClient


def _load_env() -> None:
    env_path = _REPO_ROOT / ".env"
    if env_path.is_file():
        load_dotenv(env_path)


def col_to_a1(col_1based: int) -> str:
    """1 = A, 6 = F, 27 = AA."""
    s = ""
    n = col_1based
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def sheet_range_a1(sheet_title: str, col_end: str, row_end: int) -> str:
    safe = sheet_title.replace("'", "''")
    return f"'{safe}'!A1:{col_end}{row_end}"


def _rgb(r: float, g: float, b: float) -> dict[str, float]:
    return {"red": r, "green": g, "blue": b}


def grid_range(
    sheet_id: int,
    r1: int,
    r2: int,
    c1: int,
    c2: int,
) -> dict[str, int]:
    """Полуоткрытые индексы строк/столбцов как в API: [r1,r2), [c1,c2)."""
    return {
        "sheetId": sheet_id,
        "startRowIndex": r1,
        "endRowIndex": r2,
        "startColumnIndex": c1,
        "endColumnIndex": c2,
    }


INDICATORS_RU = [
    "Выручка",
    "Количество сделок",
    "Средний чек",
    "Конверсия визитов",
    "Возвраты",
    "Новые клиенты",
    "Повторные заказы",
    "Выполнение плана, %",
    "Операционные расходы",
    "Маржа",
]


def simulate_table_rows(count: int) -> tuple[list[list[object]], int]:
    """Строки таблицы (без заголовка) и сумма по столбцу «Значение»."""
    rows: list[list[object]] = []
    total = 0
    for i in range(1, count + 1):
        name = random.choice(INDICATORS_RU)
        val = random.randint(5, 50_000)
        total += val
        unit = random.choice(["руб.", "шт.", "%", "ед.", "чел."])
        status = random.choice(["ОК", "В норме", "На контроле", "—"])
        note = random.choice(["", "За период", "п/п", "оценка"])
        rows.append([i, name, val, unit, status, note])
    return rows, total


def build_report_values(
    date_from: str,
    date_to: str,
    department: str,
    report_kind: str,
    author: str,
    rows_count: int,
) -> tuple[list[list[object]], int, int, int]:
    """
    Возвращает (values, sheet_id placeholder unused, header_row_idx, first_data_row_idx).
    header_row_idx и first_data_row_idx — 0-based индексы строк на листе.
    """
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    data_rows, total_sum = simulate_table_rows(rows_count)

    values: list[list[object]] = []
    values.append(["СВОДНЫЙ ОТЧЁТ (симуляция)", "", "", "", "", ""])
    values.append([])
    values.append(["Период", f"с {date_from} по {date_to}", "", "", "", ""])
    values.append(["Отдел / направление", department, "Тип отчёта", report_kind, "", ""])
    values.append(["Исполнитель", author, "Сформировано", now, "", ""])
    values.append([])
    values.append(["№", "Показатель", "Значение", "Ед. изм.", "Статус", "Примечание"])

    header_row = 6
    first_data = 7
    values.extend(data_rows)
    values.append([])
    values.append(["", "ИТОГО (сумма по «Значение»)", total_sum, "", "", ""])

    return values, 0, header_row, first_data


def apply_report_formatting(
    client: GoogleSheetsClient,
    sheet_id: int,
    num_rows: int,
    header_row: int,
    first_data_row: int,
    num_data_rows: int,
) -> None:
    """Объединения, шрифты, заливка шапки таблицы, границы, ширина колонок."""
    table_end_row = num_rows  # endRowIndex (exclusive) — до конца листа с итогом

    requests: list[dict] = [
        {
            "mergeCells": {
                "range": grid_range(sheet_id, 0, 1, 0, 6),
                "mergeType": "MERGE_ALL",
            }
        },
        {
            "repeatCell": {
                "range": grid_range(sheet_id, 0, 1, 0, 6),
                "cell": {
                    "userEnteredFormat": {
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                        "textFormat": {"bold": True, "fontSize": 14},
                    }
                },
                "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment,textFormat)",
            }
        },
        {
            "repeatCell": {
                "range": grid_range(sheet_id, 2, 5, 0, 1),
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True},
                        "horizontalAlignment": "LEFT",
                    }
                },
                "fields": "userEnteredFormat(textFormat,horizontalAlignment)",
            }
        },
        {
            "repeatCell": {
                "range": grid_range(sheet_id, header_row, header_row + 1, 0, 6),
                "cell": {
                    "userEnteredFormat": {
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                        "wrapStrategy": "WRAP",
                        "textFormat": {"bold": True},
                        "backgroundColor": _rgb(0.85, 0.88, 0.95),
                    }
                },
                "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment,wrapStrategy,textFormat,backgroundColor)",
            }
        },
        {
            "repeatCell": {
                "range": grid_range(sheet_id, first_data_row, first_data_row + num_data_rows, 0, 6),
                "cell": {
                    "userEnteredFormat": {
                        "verticalAlignment": "MIDDLE",
                        "wrapStrategy": "WRAP",
                    }
                },
                "fields": "userEnteredFormat(verticalAlignment,wrapStrategy)",
            }
        },
        {
            "repeatCell": {
                "range": grid_range(
                    sheet_id, first_data_row, first_data_row + num_data_rows, 2, 3
                ),
                "cell": {
                    "userEnteredFormat": {"horizontalAlignment": "RIGHT"}
                },
                "fields": "userEnteredFormat.horizontalAlignment",
            }
        },
        {
            "repeatCell": {
                "range": grid_range(sheet_id, table_end_row - 1, table_end_row, 0, 6),
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True},
                        "backgroundColor": _rgb(0.92, 0.95, 0.92),
                    }
                },
                "fields": "userEnteredFormat(textFormat,backgroundColor)",
            }
        },
        {
            "repeatCell": {
                "range": grid_range(sheet_id, table_end_row - 1, table_end_row, 2, 3),
                "cell": {
                    "userEnteredFormat": {"horizontalAlignment": "RIGHT"}
                },
                "fields": "userEnteredFormat.horizontalAlignment",
            }
        },
        {
            "updateBorders": {
                "range": grid_range(sheet_id, header_row, table_end_row, 0, 6),
                "top": {
                    "style": "SOLID",
                    "width": 1,
                    "color": _rgb(0.4, 0.4, 0.45),
                },
                "bottom": {
                    "style": "SOLID",
                    "width": 1,
                    "color": _rgb(0.4, 0.4, 0.45),
                },
                "left": {
                    "style": "SOLID",
                    "width": 1,
                    "color": _rgb(0.4, 0.4, 0.45),
                },
                "right": {
                    "style": "SOLID",
                    "width": 1,
                    "color": _rgb(0.4, 0.4, 0.45),
                },
                "innerHorizontal": {
                    "style": "SOLID",
                    "width": 1,
                    "color": _rgb(0.75, 0.76, 0.8),
                },
                "innerVertical": {
                    "style": "SOLID",
                    "width": 1,
                    "color": _rgb(0.75, 0.76, 0.8),
                },
            }
        },
        {
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": 6,
                }
            }
        },
    ]
    client.spreadsheet_batch_update(requests)


def create_report_sheet(
    client: GoogleSheetsClient,
    date_from: str,
    date_to: str,
    department: str,
    report_kind: str,
    author: str,
    rows_count: int,
) -> tuple[str, str]:
    """
    Создаёт новый лист, пишет данные, применяет оформление.
    Возвращает (имя_листа, ссылка_на_таблицу).
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sheet_title = f"Отчёт_{stamp}"

    add_resp = client.spreadsheet_batch_update(
        [{"addSheet": {"properties": {"title": sheet_title}}}]
    )
    sheet_id = int(add_resp["replies"][0]["addSheet"]["properties"]["sheetId"])

    values, _, header_row, first_data = build_report_values(
        date_from, date_to, department, report_kind, author, rows_count
    )
    num_data_rows = rows_count
    nrows = len(values)
    end_col = col_to_a1(6)
    rng = sheet_range_a1(sheet_title, end_col, nrows)
    client.update_range(rng, values)

    apply_report_formatting(
        client,
        sheet_id,
        nrows,
        header_row,
        first_data,
        num_data_rows,
    )

    url = f"https://docs.google.com/spreadsheets/d/{client.spreadsheet_id}/edit#gid={sheet_id}"
    return sheet_title, url


class ReportApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Генератор отчётов → Google Таблица")
        self.geometry("520x380")
        self.minsize(480, 340)

        pad = {"padx": 10, "pady": 6}
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="Период: дата «с» (ДД.ММ.ГГГГ)").grid(row=0, column=0, sticky=tk.W, **pad)
        self.date_from = ttk.Entry(frm, width=28)
        self.date_from.grid(row=0, column=1, sticky=tk.EW, **pad)
        self.date_from.insert(0, "01.01.2026")

        ttk.Label(frm, text="Период: дата «по»").grid(row=1, column=0, sticky=tk.W, **pad)
        self.date_to = ttk.Entry(frm, width=28)
        self.date_to.grid(row=1, column=1, sticky=tk.EW, **pad)
        self.date_to.insert(0, "07.04.2026")

        ttk.Label(frm, text="Отдел / направление").grid(row=2, column=0, sticky=tk.W, **pad)
        self.department = ttk.Combobox(
            frm,
            width=26,
            values=["Продажи", "Маркетинг", "Склад", "Финансы", "HR", "IT"],
        )
        self.department.grid(row=2, column=1, sticky=tk.EW, **pad)
        self.department.set("Продажи")

        ttk.Label(frm, text="Тип отчёта").grid(row=3, column=0, sticky=tk.W, **pad)
        self.report_kind = ttk.Combobox(
            frm,
            width=26,
            values=["Оперативный", "Сводный за период", "KPI", "План-факт"],
        )
        self.report_kind.grid(row=3, column=1, sticky=tk.EW, **pad)
        self.report_kind.set("Сводный за период")

        ttk.Label(frm, text="Исполнитель").grid(row=4, column=0, sticky=tk.W, **pad)
        self.author = ttk.Entry(frm, width=28)
        self.author.grid(row=4, column=1, sticky=tk.EW, **pad)
        self.author.insert(0, "Иванов И.И.")

        ttk.Label(frm, text="Число строк в таблице (симуляция)").grid(row=5, column=0, sticky=tk.W, **pad)
        self.rows_count = ttk.Spinbox(frm, from_=3, to=50, width=26)
        self.rows_count.grid(row=5, column=1, sticky=tk.EW, **pad)
        self.rows_count.delete(0, tk.END)
        self.rows_count.insert(0, "10")

        frm.columnconfigure(1, weight=1)

        btn = ttk.Button(frm, text="Сформировать отчёт в Google Таблице", command=self.on_submit)
        btn.grid(row=6, column=0, columnspan=2, pady=16)

        self.status = ttk.Label(frm, text="", wraplength=480)
        self.status.grid(row=7, column=0, columnspan=2, sticky=tk.W, **pad)

    def on_submit(self) -> None:
        _load_env()
        sid = os.environ.get("GOOGLE_SPREADSHEET_ID")
        cred = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not sid or not cred:
            messagebox.showerror(
                "Настройки",
                "В .env должны быть GOOGLE_SPREADSHEET_ID и GOOGLE_APPLICATION_CREDENTIALS.",
            )
            return

        d1 = self.date_from.get().strip()
        d2 = self.date_to.get().strip()
        dept = self.department.get().strip() or "—"
        kind = self.report_kind.get().strip() or "—"
        author = self.author.get().strip() or "—"
        try:
            rc = int(self.rows_count.get())
        except ValueError:
            messagebox.showerror("Ошибка", "Укажите целое число строк.")
            return
        if rc < 3 or rc > 50:
            messagebox.showerror("Ошибка", "Число строк: от 3 до 50.")
            return

        self.status.config(text="Отправка в Google Sheets…")
        self.update_idletasks()

        try:
            client = GoogleSheetsClient(sid, credentials_path=cred)
            title, url = create_report_sheet(client, d1, d2, dept, kind, author, rc)
        except HttpError as e:
            self.status.config(text="")
            messagebox.showerror("Google API", str(e))
            return
        except Exception as e:  # noqa: BLE001
            self.status.config(text="")
            messagebox.showerror("Ошибка", str(e))
            return

        self.status.config(text=f"Готово. Лист: {title}")
        messagebox.showinfo(
            "Готово",
            f"Отчёт создан на новом листе «{title}».\n\nОткрыть таблицу можно по ссылке (скопируйте):\n{url}",
        )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass
    _load_env()
    app = ReportApp()
    app.mainloop()


if __name__ == "__main__":
    main()
