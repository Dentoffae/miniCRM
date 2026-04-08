"""
Google Sheets API (v4) с OAuth-учётными данными пользователя (те же вызовы API, что в google_sheets_crud).
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)


class GoogleSheetsOAuthClient:
    """Таблица по ID; credentials — из GoogleDriveOAuthClient.credentials."""

    def __init__(
        self,
        spreadsheet_id: str,
        *,
        credentials: Credentials,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id
        creds = credentials
        if creds.requires_scopes:
            creds = creds.with_scopes(list(SCOPES))
        if not creds.valid:
            creds.refresh(Request())
        self._creds = creds
        self._service = build("sheets", "v4", credentials=creds, cache_discovery=False)

    @property
    def values(self) -> Any:
        return self._service.spreadsheets().values()

    def get_values(self, range_a1: str) -> list[list[Any]]:
        result = (
            self.values.get(spreadsheetId=self.spreadsheet_id, range=range_a1).execute()
        )
        return result.get("values", [])

    def list_sheet_titles(self) -> list[str]:
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
        meta = (
            self._service.spreadsheets()
            .get(
                spreadsheetId=self.spreadsheet_id,
                fields="sheets(properties)",
            )
            .execute()
        )
        return [s.get("properties", {}) for s in meta.get("sheets", [])]

    def update_range(
        self,
        range_a1: str,
        values: Sequence[Sequence[Any]],
        *,
        value_input_option: str = "USER_ENTERED",
    ) -> dict[str, Any]:
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
        payload = {
            "valueInputOption": value_input_option,
            "data": list(data),
        }
        return (
            self.values.batchUpdate(spreadsheetId=self.spreadsheet_id, body=payload).execute()
        )

    def clear_range(self, range_a1: str) -> dict[str, Any]:
        return (
            self.values.clear(spreadsheetId=self.spreadsheet_id, range=range_a1).execute()
        )

    def spreadsheet_batch_update(
        self, requests: Sequence[dict[str, Any]]
    ) -> dict[str, Any]:
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


__all__ = ["GoogleSheetsOAuthClient", "HttpError", "SCOPES"]
