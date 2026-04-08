"""Обёртки над рабочими клиентами Google (OAuth в GUI)."""

from google_integration.google_drive import GoogleDriveOAuthClient, HttpError
from google_integration.google_sheets import GoogleSheetsOAuthClient

__all__ = ["GoogleDriveOAuthClient", "GoogleSheetsOAuthClient", "HttpError"]

# Примечание: импорты абсолютные — корень проекта должен быть в sys.path (делает crm_gui).
