"""FCM (Firebase Cloud Messaging) push yuborish — HTTP v1 API orqali.

Yangi og'ir kutubxona (firebase-admin) qo'shmaslik uchun, allaqachon mavjud
`google-auth` (service account credentials) + `requests` ishlatiladi.

Sozlash (Render env):
- `FIREBASE_SERVICE_ACCOUNT` — Firebase service account JSON'ining O'ZI (string),
  YOKI
- `GOOGLE_APPLICATION_CREDENTIALS` — service account JSON faylining yo'li.

Service account Firebase Console → Project Settings → Service accounts →
"Generate new private key" dan olinadi. `project_id` shu JSON ichidan olinadi.
"""
import json
import os
import threading
from typing import Optional, Tuple

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_FCM_ENDPOINT = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

# Credentials va project_id bir marta yuklanadi (thread-safe).
_lock = threading.Lock()
_credentials = None
_project_id: Optional[str] = None
_load_failed = False


def _load_service_account_info() -> Optional[dict]:
    """Service account JSON'ini env'dan o'qiydi (string yoki fayl yo'li)."""
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    return None


def _ensure_credentials() -> bool:
    """Credentials va project_id'ni bir marta tayyorlaydi. Sozlanmagan bo'lsa False."""
    global _credentials, _project_id, _load_failed

    if _credentials is not None and _project_id:
        return True
    if _load_failed:
        return False

    with _lock:
        if _credentials is not None and _project_id:
            return True

        info = _load_service_account_info()
        if not info:
            _load_failed = True
            return False

        try:
            _credentials = service_account.Credentials.from_service_account_info(
                info, scopes=[_FCM_SCOPE]
            )
        except (ValueError, KeyError):
            _load_failed = True
            return False

        _project_id = info.get("project_id")
        if not _project_id:
            _load_failed = True
            return False

    return True


def _access_token() -> Optional[str]:
    """Joriy OAuth2 access tokenni qaytaradi (muddati tugagan bo'lsa yangilaydi)."""
    if not _ensure_credentials():
        return None
    if not _credentials.valid:
        _credentials.refresh(Request())
    return _credentials.token


def is_configured() -> bool:
    """FCM sozlanganmi (server push yubora oladimi)."""
    return _ensure_credentials()


def send_to_token(
    token: str,
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> Tuple[bool, bool]:
    """Bitta qurilma tokeniga push yuboradi.

    Qaytadi: (ok, unregistered)
    - ok=True — yuborildi.
    - unregistered=True — token endi yaroqsiz (UNREGISTERED/NOT_FOUND),
      chaqiruvchi uni bazadan o'chirib tashlashi kerak.
    """
    access_token = _access_token()
    if not access_token:
        return (False, False)

    message = {
        "message": {
            "token": token,
            "notification": {"title": title, "body": body},
            "android": {"priority": "high"},
            "apns": {
                "payload": {"aps": {"sound": "default"}},
            },
        }
    }
    if data:
        # FCM data qiymatlari faqat string bo'lishi mumkin
        message["message"]["data"] = {k: str(v) for k, v in data.items()}

    url = _FCM_ENDPOINT.format(project_id=_project_id)
    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            data=json.dumps(message),
            timeout=10,
        )
    except requests.RequestException:
        return (False, False)

    if resp.status_code == 200:
        return (True, False)

    # Yaroqsiz token: 404 (NOT_FOUND) yoki 400 (UNREGISTERED) — o'chirish kerak.
    unregistered = False
    if resp.status_code in (400, 404):
        try:
            err = resp.json().get("error", {})
            status = err.get("status", "")
            details = json.dumps(err.get("details", []))
            if status in ("NOT_FOUND", "UNREGISTERED") or "UNREGISTERED" in details:
                unregistered = True
        except (ValueError, AttributeError):
            unregistered = resp.status_code == 404

    return (False, unregistered)
