"""
Клиент Google Sheets API (v4) через сервисный аккаунт.
Импорт в другое приложение: from google_sheets_crud import GoogleSheetsClient
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)


class GoogleSheetsClient:
    """CRUD и чтение метаданных таблицы по ID и JSON-ключу сервисного аккаунта."""

    def __init__(
        self,
        spreadsheet_id: str,
        credentials_path: str | Path | None = None,
        *,
        credentials: service_account.Credentials | None = None,
    ) -> None:
        """
        :param spreadsheet_id: ID таблицы из URL.
        :param credentials_path: путь к JSON ключу (если не задан — берётся GOOGLE_APPLICATION_CREDENTIALS).
        :param credentials: готовые credentials (если уже загружены сами).
        """
        self.spreadsheet_id = spreadsheet_id
        if credentials is not None:
            creds = credentials
            if creds.requires_scopes:
                creds = creds.with_scopes(SCOPES)
        else:
            path = credentials_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            if not path:
                raise ValueError(
                    "Укажите credentials_path или переменную окружения GOOGLE_APPLICATION_CREDENTIALS"
                )
            creds = service_account.Credentials.from_service_account_file(
                str(path), scopes=SCOPES
            )
        if not creds.valid:
            creds.refresh(Request())
        self._creds = creds
        self._service = build("sheets", "v4", credentials=creds, cache_discovery=False)

    @property
    def values(self) -> Any:
        return self._service.spreadsheets().values()

    # --- Read ---

    def get_values(self, range_a1: str) -> list[list[Any]]:
        """Читает диапазон в нотации A1 (например 'Лист1!A1:C10' или только имя листа — все заполненные ячейки)."""
        result = (
            self.values.get(spreadsheetId=self.spreadsheet_id, range=range_a1).execute()
        )
        return result.get("values", [])

    def list_sheet_titles(self) -> list[str]:
        """Список имён листов по порядку."""
        meta = (
            self._service.spreadsheets()
            .get(spreadsheetId=self.spreadsheet_id, fields="sheets(properties(title))")
            .execute()
        )
        return [
            s["properties"]["title"]
            for s in meta.get("sheets", [])
            if "properties" in s
        ]

    def get_sheet_properties(self) -> list[dict[str, Any]]:
        """Свойства листов: title, sheetId, index и др."""
        meta = (
            self._service.spreadsheets()
            .get(
                spreadsheetId=self.spreadsheet_id,
                fields="sheets(properties)",
            )
            .execute()
        )
        return [s.get("properties", {}) for s in meta.get("sheets", [])]

    def get_sheets_grid_row_counts(self) -> dict[str, int]:
        """Число строк сетки каждого листа (как в документе), нужно для диапазонов вида 3:N."""
        meta = (
            self._service.spreadsheets()
            .get(
                spreadsheetId=self.spreadsheet_id,
                fields="sheets(properties(title,gridProperties(rowCount)))",
            )
            .execute()
        )
        out: dict[str, int] = {}
        for s in meta.get("sheets", []):
            p = s.get("properties", {})
            title = p.get("title")
            if not title:
                continue
            grid = p.get("gridProperties") or {}
            out[title] = int(grid.get("rowCount") or 0)
        return out

    def read_all_sheets(self) -> dict[str, list[list[Any]]]:
        """Читает все заполненные данные по каждому листу (ключ — имя листа)."""
        out: dict[str, list[list[Any]]] = {}
        for title in self.list_sheet_titles():
            out[title] = self.get_values(title)
        return out

    # --- Create (append) ---

    def append_rows(
        self,
        range_a1: str,
        values: Sequence[Sequence[Any]],
        *,
        value_input_option: str = "USER_ENTERED",
        insert_data_option: str = "INSERT_ROWS",
    ) -> dict[str, Any]:
        """
        Добавляет строки в конец таблицы в указанном диапазоне (обычно имя листа или 'Лист1!A1').
        insert_data_option: INSERT_ROWS | OVERWRITE
        """
        body = {"values": [list(row) for row in values]}
        return (
            self.values.append(
                spreadsheetId=self.spreadsheet_id,
                range=range_a1,
                valueInputOption=value_input_option,
                insertDataOption=insert_data_option,
                body=body,
            ).execute()
        )

    # --- Update ---

    def update_range(
        self,
        range_a1: str,
        values: Sequence[Sequence[Any]],
        *,
        value_input_option: str = "USER_ENTERED",
    ) -> dict[str, Any]:
        """Перезаписывает диапазон; размер values должен соответствовать range (или API расширит при необходимости)."""
        body = {"values": [list(row) for row in values]}
        return (
            self.values.update(
                spreadsheetId=self.spreadsheet_id,
                range=range_a1,
                valueInputOption=value_input_option,
                body=body,
            ).execute()
        )

    def batch_update_values(
        self,
        data: Iterable[dict[str, Any]],
        *,
        value_input_option: str = "USER_ENTERED",
    ) -> dict[str, Any]:
        """
        Несколько диапазонов за один запрос.
        data: [{"range": "Лист1!A1", "values": [["a"]]}, ...]
        """
        payload = {
            "valueInputOption": value_input_option,
            "data": list(data),
        }
        return (
            self.values.batchUpdate(spreadsheetId=self.spreadsheet_id, body=payload).execute()
        )

    # --- Delete ---

    def clear_range(self, range_a1: str) -> dict[str, Any]:
        """Очищает значения в диапазоне."""
        return (
            self.values.clear(spreadsheetId=self.spreadsheet_id, range=range_a1).execute()
        )

    def delete_rows(
        self,
        sheet_id: int,
        start_index: int,
        end_index: int,
    ) -> dict[str, Any]:
        """Удаляет строки [start_index, end_index) на листе с данным sheet_id (0-based)."""
        body = {
            "requests": [
                {
                    "deleteDimension": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "ROWS",
                            "startIndex": start_index,
                            "endIndex": end_index,
                        }
                    }
                }
            ]
        }
        return (
            self._service.spreadsheets()
            .batchUpdate(spreadsheetId=self.spreadsheet_id, body=body)
            .execute()
        )

    def spreadsheet_batch_update(
        self, requests: Sequence[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Структура и оформление листа: addSheet, mergeCells, repeatCell, размеры колонок и т.д.
        См. https://developers.google.com/sheets/api/reference/rest/v4/spreadsheets/batchUpdate
        """
        body = {"requests": list(requests)}
        return (
            self._service.spreadsheets()
            .batchUpdate(spreadsheetId=self.spreadsheet_id, body=body)
            .execute()
        )

    def sheet_id_by_title(self, title: str) -> int:
        for p in self.get_sheet_properties():
            if p.get("title") == title:
                sid = p.get("sheetId")
                if sid is not None:
                    return int(sid)
        raise KeyError(f"Лист не найден: {title!r}")


__all__ = ["GoogleSheetsClient", "SCOPES", "HttpError"]


def _load_dotenv_if_present() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.is_file():
        load_dotenv(env_path)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass
    _load_dotenv_if_present()
    sid = os.environ.get("GOOGLE_SPREADSHEET_ID")
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not sid or not cred_path:
        raise SystemExit(
            "Задайте GOOGLE_SPREADSHEET_ID и GOOGLE_APPLICATION_CREDENTIALS в .env или окружении."
        )
    client = GoogleSheetsClient(sid, credentials_path=cred_path)
    all_data = client.read_all_sheets()
    for sheet_name, rows in all_data.items():
        print(f"=== {sheet_name} ===")
        for row in rows:
            print(row)
        print()
