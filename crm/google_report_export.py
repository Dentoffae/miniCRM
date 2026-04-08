"""
Выгрузка вкладки CRM в новую Google Таблицу (OAuth на машине пользователя).
Используются только классы из google_integration.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

Kind = Literal["clients", "deals", "tasks"]

_KIND_TITLE = {
    "clients": "Клиенты",
    "deals": "Сделки",
    "tasks": "Задачи",
}


def _analyze(kind: Kind, records: list[dict]) -> list[list[Any]]:
    """Сводка над таблицей."""
    n = len(records)
    lines: list[list[Any]] = [
        ["Показатель", "Значение"],
        ["Тип отчёта", _KIND_TITLE[kind]],
        ["Всего строк", n],
    ]
    if kind == "clients":
        act = sum(1 for r in records if (r.get("status") or "") == "active")
        arch = sum(1 for r in records if (r.get("status") or "") == "archived")
        lines.append(["Статус «active»", act])
        lines.append(["Статус «archived»", arch])
    elif kind == "deals":
        total_amt = 0.0
        for r in records:
            a = r.get("amount")
            if a is not None:
                try:
                    total_amt += float(a)
                except (TypeError, ValueError):
                    pass
        lines.append(["Сумма amount (числовые строки)", round(total_amt, 2)])
        statuses: dict[str, int] = {}
        for r in records:
            s = str(r.get("status") or "")
            statuses[s] = statuses.get(s, 0) + 1
        for s, c in sorted(statuses.items(), key=lambda x: -x[1])[:8]:
            lines.append([f"Статус «{s}»", c])
    else:
        done = sum(1 for r in records if r.get("completed") is True)
        lines.append(["Выполнено", done])
        lines.append(["Не выполнено", n - done])
    lines.append(["Сформировано (UTC)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")])
    return lines


def _columns_and_rows(kind: Kind, records: list[dict]) -> tuple[list[str], list[list[Any]]]:
    if kind == "clients":
        cols = ["id", "name", "email", "phone", "company", "notes", "status", "created_at", "updated_at"]
    elif kind == "deals":
        cols = [
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
    else:
        cols = [
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
    rows: list[list[Any]] = []
    for r in records:
        row: list[Any] = []
        for c in cols:
            v = r.get(c)
            if c == "completed" and isinstance(v, bool):
                row.append("да" if v else "нет")
            else:
                row.append("" if v is None else v)
        rows.append(row)
    return cols, rows


def _a1_sheet(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def export_to_google_sheet(
    *,
    kind: Kind,
    records: list[dict],
    folder_id: str,
    oauth_client_json: str = "",
    oauth_token_json: str = "",
    drive_client: Any = None,
) -> dict[str, Any]:
    from google_integration.google_drive import GoogleDriveOAuthClient
    from google_integration.google_sheets import GoogleSheetsOAuthClient

    if not folder_id.strip():
        raise ValueError("Заполните настройки Google: ID папки Drive.")

    if drive_client is not None:
        drive = drive_client
    else:
        if not oauth_client_json.strip() or not oauth_token_json.strip():
            raise ValueError("Заполните настройки Google: JSON клиента, token.json и ID папки.")
        drive = GoogleDriveOAuthClient(
            client_secrets_path=oauth_client_json.strip(),
            token_path=oauth_token_json.strip(),
        )
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    safe_kind = _KIND_TITLE[kind]
    title = f"CRM_{safe_kind}_{stamp}"

    meta = drive.create_google_spreadsheet(title, folder_id.strip())
    spreadsheet_id = meta["id"]
    sheets = GoogleSheetsOAuthClient(spreadsheet_id, credentials=drive.credentials)

    sheet_titles = sheets.list_sheet_titles()
    sheet_name = sheet_titles[0] if sheet_titles else "Sheet1"

    summary = _analyze(kind, records)
    cols, data_rows = _columns_and_rows(kind, records)

    top: list[list[Any]] = [[f"Отчёт CRM — {safe_kind}"], []]
    gap: list[list[Any]] = [[], ["Данные"], []]
    all_values = top + summary + gap + [cols] + data_rows

    header_row_idx = len(top) + len(summary) + len(gap)

    q = _a1_sheet(sheet_name)
    sheets.clear_range(f"{q}!A:ZZ")
    sheets.update_range(f"{q}!A1", all_values)

    sid = sheets.sheet_id_by_title(sheet_name)
    ncols = max(len(cols), 2)

    sheets.spreadsheet_batch_update(
        [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sid,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": 3,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"bold": True, "fontSize": 14},
                        }
                    },
                    "fields": "userEnteredFormat.textFormat",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sid,
                        "startRowIndex": header_row_idx,
                        "endRowIndex": header_row_idx + 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": ncols,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 0.85, "green": 0.88, "blue": 0.98},
                            "textFormat": {"bold": True},
                            "horizontalAlignment": "CENTER",
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
                }
            },
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sid,
                        "gridProperties": {"frozenRowCount": header_row_idx + 1},
                    },
                    "fields": "gridProperties.frozenRowCount",
                }
            },
        ]
    )

    return {
        "spreadsheet_id": spreadsheet_id,
        "title": title,
        "webViewLink": meta.get("webViewLink") or "",
        "kind": kind,
        "rows_written": len(all_values),
    }
