"""
Клиент Google Drive API (v3): сервисный аккаунт (GoogleDriveClient)
и личный аккаунт OAuth2 (GoogleDriveOAuthClient).
Импорт: from google_drive import GoogleDriveClient, GoogleDriveOAuthClient
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# Полный доступ к файлам, которые видит сервисный аккаунт (его Drive и расшаренное).
SCOPES = ("https://www.googleapis.com/auth/drive",)

# OAuth: Drive + Sheets (отчёты из GUI в Google Таблицы).
OAUTH_DRIVE_SCOPES = (
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
)

MIME_GOOGLE_DOC = "application/vnd.google-apps.document"
MIME_GOOGLE_SHEET = "application/vnd.google-apps.spreadsheet"

_DEFAULT_LIST_FIELDS = (
    "nextPageToken, files(id, name, mimeType, parents, createdTime, "
    "modifiedTime, size, webViewLink, trashed)"
)


class GoogleDriveClient:
    """CRUD и листинг файлов Drive по JSON-ключу сервисного аккаунта."""

    def __init__(
        self,
        credentials_path: str | Path | None = None,
        *,
        credentials: service_account.Credentials | None = None,
    ) -> None:
        """
        :param credentials_path: путь к JSON ключу (если не задан — GOOGLE_APPLICATION_CREDENTIALS).
        :param credentials: готовые credentials.
        """
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
        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)

    @property
    def files(self) -> Any:
        return self._service.files()

    # --- Read ---

    def list_files(
        self,
        *,
        query: str | None = None,
        page_size: int = 100,
        fields: str = _DEFAULT_LIST_FIELDS,
        include_all_drives: bool = True,
        corpora: str | None = None,
        drive_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Список файлов с пагинацией. query — выражение Drive query API, например:
        "'FOLDER_ID' in parents and trashed = false"
        """
        out: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "pageSize": min(page_size, 1000),
                "fields": fields,
                "supportsAllDrives": include_all_drives,
                "includeItemsFromAllDrives": include_all_drives,
            }
            if query:
                kwargs["q"] = query
            if page_token:
                kwargs["pageToken"] = page_token
            if corpora:
                kwargs["corpora"] = corpora
            if drive_id:
                kwargs["driveId"] = drive_id
            result = self.files.list(**kwargs).execute()
            out.extend(result.get("files", []))
            page_token = result.get("nextPageToken")
            if not page_token:
                break
        return out

    def list_files_in_folder(self, folder_id: str, *, trashed: bool = False) -> list[dict[str, Any]]:
        """Все непосредственные дочерние элементы папки."""
        trash_clause = "trashed = true" if trashed else "trashed = false"
        q = f"'{folder_id}' in parents and {trash_clause}"
        return self.list_files(query=q)

    def get_file(
        self,
        file_id: str,
        *,
        fields: str = "id, name, mimeType, parents, createdTime, modifiedTime, size, webViewLink, trashed",
    ) -> dict[str, Any]:
        """Метаданные одного файла."""
        return (
            self.files.get(
                fileId=file_id,
                fields=fields,
                supportsAllDrives=True,
            ).execute()
        )

    def download_file_bytes(self, file_id: str) -> bytes:
        """Скачивает бинарное содержимое (не для native Google Docs — для них экспортируйте отдельно)."""
        request = self.files.get_media(fileId=file_id, supportsAllDrives=True)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return fh.getvalue()

    # --- Create ---

    def create_file(
        self,
        name: str,
        *,
        mime_type: str = "application/octet-stream",
        parents: list[str] | None = None,
        content: bytes | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """
        Создаёт файл. Без content — только метаданные (пустой файл / Google Apps по mime_type).
        С content — загрузка тела (не подходит для составного создания Google Docs из HTML без convert).
        """
        body: dict[str, Any] = {"name": name, "mimeType": mime_type}
        if parents:
            body["parents"] = parents
        if description:
            body["description"] = description

        if content is None:
            return (
                self.files.create(
                    body=body,
                    fields="id, name, mimeType, parents, webViewLink",
                    supportsAllDrives=True,
                ).execute()
            )

        media = MediaIoBaseUpload(
            io.BytesIO(content),
            mimetype=mime_type,
            resumable=True,
        )
        return (
            self.files.create(
                body=body,
                media_body=media,
                fields="id, name, mimeType, parents, size, webViewLink",
                supportsAllDrives=True,
            ).execute()
        )

    # --- Update ---

    def update_metadata(
        self,
        file_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        add_parents: list[str] | None = None,
        remove_parents: list[str] | None = None,
    ) -> dict[str, Any]:
        """Переименование, описание, смена родителей (перемещение)."""
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description

        kwargs: dict[str, Any] = {
            "fileId": file_id,
            "body": body,
            "fields": "id, name, mimeType, parents, modifiedTime",
            "supportsAllDrives": True,
        }
        if add_parents:
            kwargs["addParents"] = ",".join(add_parents)
        if remove_parents:
            kwargs["removeParents"] = ",".join(remove_parents)

        return self.files.update(**kwargs).execute()

    def update_file_content(
        self,
        file_id: str,
        content: bytes,
        *,
        mime_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        """Обновляет содержимое существующего файла."""
        media = MediaIoBaseUpload(
            io.BytesIO(content),
            mimetype=mime_type,
            resumable=True,
        )
        return (
            self.files.update(
                fileId=file_id,
                media_body=media,
                fields="id, name, mimeType, size, modifiedTime",
                supportsAllDrives=True,
            ).execute()
        )

    def trash_file(self, file_id: str) -> dict[str, Any]:
        """Перемещает в корзину."""
        return (
            self.files.update(
                fileId=file_id,
                body={"trashed": True},
                fields="id, trashed",
                supportsAllDrives=True,
            ).execute()
        )

    def untrash_file(self, file_id: str) -> dict[str, Any]:
        """Восстанавливает из корзины."""
        return (
            self.files.update(
                fileId=file_id,
                body={"trashed": False},
                fields="id, trashed",
                supportsAllDrives=True,
            ).execute()
        )

    # --- Delete ---

    def delete_file(self, file_id: str) -> None:
        """Безвозвратное удаление (не корзина)."""
        self.files.delete(fileId=file_id, supportsAllDrives=True).execute()


_PROJECT_DIR = Path(__file__).resolve().parent


def _resolve_oauth_client_secrets_path(client_secrets: str | Path) -> Path:
    """Абсолютный путь к JSON клиента: как задано, либо рядом с модулем (папка проекта)."""
    p = Path(client_secrets)
    if p.is_file():
        return p.resolve()
    alt = (_PROJECT_DIR / p).resolve()
    if alt.is_file():
        return alt
    raise FileNotFoundError(
        "Не найден OAuth client JSON. В .env укажите реальное имя файла "
        "(из Google Cloud → Credentials → скачанный client_secret_….json), "
        f"не плейсхолдер с «....». Искали: {p} и {alt}"
    )


def _resolve_oauth_token_path(token: str | Path) -> Path:
    """Путь к token.json: относительные пути считаются от папки проекта."""
    t = Path(token)
    if t.is_absolute():
        return t.resolve()
    return (_PROJECT_DIR / t).resolve()


def _oauth_user_credentials(
    client_secrets_path: str | Path,
    token_path: str | Path,
    scopes: Sequence[str],
) -> Credentials:
    """
    Загружает или запрашивает OAuth2-токен пользователя, сохраняет в token_path.
    При первом запуске откроется браузер (Installed App / Desktop).
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    token_path = Path(token_path)
    creds: Credentials | None = None
    if token_path.is_file():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes=list(scopes))

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(client_secrets_path),
                scopes=list(scopes),
            )
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return creds


class GoogleDriveOAuthClient:
    """
    Drive API от имени пользователя (OAuth2).
    client_secret JSON — тип Desktop/Installed из Google Cloud Console.
    """

    def __init__(
        self,
        client_secrets_path: str | Path | None = None,
        token_path: str | Path | None = None,
        *,
        scopes: Sequence[str] | None = None,
        credentials: Credentials | None = None,
    ) -> None:
        """
        :param client_secrets_path: JSON с client_id/client_secret (installed). Иначе GOOGLE_OAUTH_CLIENT_SECRETS.
        :param token_path: файл для сохранения refresh/access token. Иначе GOOGLE_OAUTH_TOKEN_PATH или token.json рядом с модулем.
        :param credentials: готовые user Credentials (если уже есть).
        """
        use_scopes = tuple(scopes) if scopes is not None else OAUTH_DRIVE_SCOPES

        if credentials is not None:
            creds = credentials
            if creds.requires_scopes:
                creds = creds.with_scopes(list(use_scopes))
        else:
            secrets = client_secrets_path or os.environ.get("GOOGLE_OAUTH_CLIENT_SECRETS")
            if not secrets:
                raise ValueError(
                    "Укажите client_secrets_path или переменную окружения GOOGLE_OAUTH_CLIENT_SECRETS"
                )
            tok_raw = (
                token_path
                or os.environ.get("GOOGLE_OAUTH_TOKEN_PATH")
                or (_PROJECT_DIR / "token.json")
            )
            secrets_resolved = _resolve_oauth_client_secrets_path(secrets)
            tok = _resolve_oauth_token_path(tok_raw)
            creds = _oauth_user_credentials(secrets_resolved, tok, use_scopes)

        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                raise RuntimeError("OAuth credentials недействительны; удалите token.json и пройдите вход снова.")

        self._creds = creds
        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)

    @property
    def credentials(self) -> Credentials:
        """OAuth-учётные данные пользователя — для Google Sheets API и др."""
        return self._creds

    @property
    def files(self) -> Any:
        return self._service.files()

    def create_google_document(
        self,
        name: str,
        folder_id: str,
        *,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Создаёт пустой Google Doc в указанной папке (от имени пользователя)."""
        body: dict[str, Any] = {
            "name": name,
            "mimeType": MIME_GOOGLE_DOC,
            "parents": [folder_id],
        }
        if description:
            body["description"] = description
        return (
            self.files.create(
                body=body,
                fields="id, name, mimeType, parents, webViewLink, createdTime",
                supportsAllDrives=True,
            ).execute()
        )

    def create_google_spreadsheet(
        self,
        name: str,
        folder_id: str,
        *,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Создаёт пустую Google Таблицу в указанной папке (от имени пользователя)."""
        body: dict[str, Any] = {
            "name": name,
            "mimeType": MIME_GOOGLE_SHEET,
            "parents": [folder_id],
        }
        if description:
            body["description"] = description
        return (
            self.files.create(
                body=body,
                fields="id, name, mimeType, parents, webViewLink, createdTime",
                supportsAllDrives=True,
            ).execute()
        )


__all__ = [
    "GoogleDriveClient",
    "GoogleDriveOAuthClient",
    "SCOPES",
    "OAUTH_DRIVE_SCOPES",
    "MIME_GOOGLE_DOC",
    "MIME_GOOGLE_SHEET",
    "HttpError",
]


def _load_dotenv_if_present() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    here = Path(__file__).resolve().parent
    for base in (here.parent, here):
        env_path = base / ".env"
        if env_path.is_file():
            load_dotenv(env_path)
            return


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass
    _load_dotenv_if_present()
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not cred_path:
        raise SystemExit(
            "Задайте GOOGLE_APPLICATION_CREDENTIALS в .env (путь к JSON сервисного аккаунта)."
        )
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")

    client = GoogleDriveClient(credentials_path=cred_path)
    if folder_id:
        print(f"Файлы в папке GOOGLE_DRIVE_FOLDER_ID={folder_id!r}:\n")
        items = client.list_files_in_folder(folder_id)
    else:
        print(
            "Список файлов (весь доступный Drive сервисного аккаунта). "
            "Чтобы ограничить папкой, задайте GOOGLE_DRIVE_FOLDER_ID в .env.\n"
        )
        items = client.list_files(query="trashed = false")

    if not items:
        print("(пусто)")
    else:
        for f in items:
            mid = f.get("mimeType") or ""
            name = f.get("name") or ""
            fid = f.get("id") or ""
            modified = f.get("modifiedTime") or ""
            size = f.get("size")
            line = f"- {name!r} | id={fid} | {mid} | modified={modified}"
            if size is not None:
                line += f" | size={size}"
            print(line)
    print(f"\nВсего: {len(items)}")
