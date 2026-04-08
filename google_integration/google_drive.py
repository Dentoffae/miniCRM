"""
Доступ к Google Drive (OAuth) для GUI. Реализация — в пакете google/.
"""

from __future__ import annotations

import sys
from pathlib import Path

_g = Path(__file__).resolve().parent.parent / "google"
if _g.is_dir() and str(_g) not in sys.path:
    sys.path.insert(0, str(_g))

from google_drive import GoogleDriveOAuthClient  # noqa: E402
from googleapiclient.errors import HttpError  # noqa: E402

__all__ = ["GoogleDriveOAuthClient", "HttpError"]
