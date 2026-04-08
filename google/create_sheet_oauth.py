"""
Один раз запускаешь: python create_sheet_oauth.py
Создаёт новую Google Таблицу в папке из GOOGLE_DRIVE_FOLDER_ID (.env).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from google_drive import GoogleDriveOAuthClient


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    if not folder_id:
        raise SystemExit(
            "В .env задай GOOGLE_DRIVE_FOLDER_ID (ID папки из URL Drive …/folders/XXX)."
        )

    client = GoogleDriveOAuthClient()
    new_sheet = client.create_google_spreadsheet("Новая таблица (OAuth)", folder_id)
    print("Готово.")
    print("ID таблицы:", new_sheet.get("id"))
    print("Ссылка:", new_sheet.get("webViewLink"))


if __name__ == "__main__":
    main()
