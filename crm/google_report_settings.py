"""Персистентные настройки OAuth-отчётов Google для GUI (текстовый JSON)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT: dict[str, str] = {
    "oauth_client_json": "",
    "oauth_token_json": "",
    "drive_folder_id": "",
}


def settings_path(base: Path) -> Path:
    return base / "google_report_settings.json"


def load_settings(base: Path) -> dict[str, str]:
    p = settings_path(base)
    if not p.is_file():
        return dict(DEFAULT)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        out = dict(DEFAULT)
        for k in DEFAULT:
            if k in raw and isinstance(raw[k], str):
                out[k] = raw[k].strip()
        return out
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT)


def save_settings(base: Path, data: dict[str, Any]) -> None:
    p = settings_path(base)
    out = dict(DEFAULT)
    for k in DEFAULT:
        v = data.get(k, "")
        out[k] = (v or "").strip() if isinstance(v, str) else ""
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_oauth_client_json_path(path: str) -> str | None:
    """
    Проверяет, что в первом поле — OAuth client (Desktop/Web), а не сервисный аккаунт.
    Возвращает текст ошибки для пользователя или None.
    """
    p = Path(path.strip())
    if not p.is_file():
        return f"Файл OAuth-клиента не найден:\n{p}"
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        return f"Не удалось прочитать JSON клиента: {e}"
    if isinstance(raw, dict) and raw.get("type") == "service_account":
        return (
            "В первом поле указан ключ сервисного аккаунта. Нужен OAuth 2.0 Client ID "
            "типа «Desktop» (файл client_secret_….json из Google Cloud → Credentials)."
        )
    if not isinstance(raw, dict) or ("installed" not in raw and "web" not in raw):
        return (
            "В первом поле ожидается JSON OAuth-клиента с секцией «installed» или «web» "
            "(скачанный client_secret_….json)."
        )
    return None


def validate_token_json_path(path: str) -> str | None:
    """
    Файл token может отсутствовать (создастся при входе).
    Если файл есть — это не должен быть client_secret и не service account.
    """
    p = Path(path.strip())
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        return f"Не удалось прочитать файл token: {e}"
    if not isinstance(raw, dict):
        return "Файл token должен быть JSON-объектом."
    if raw.get("type") == "service_account":
        return "Во втором поле не должен быть ключ сервисного аккаунта. Укажите путь к token.json или оставьте значение по умолчанию."
    if "installed" in raw or "web" in raw:
        return (
            "Во втором поле указан client_secret (OAuth-клиент), а не token. "
            "Поменяйте файлы местами: client_secret — в первом поле, во втором — отдельный файл "
            "token.json (он появится после первого входа через браузер) или путь по умолчанию."
        )
    return None
