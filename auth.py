import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from database import get_db
from models import User, RefreshToken

# JWT sozlamalari. Maxfiy kalit env'dan olinadi (Render'ga JWT_SECRET qo'shing).
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me")
JWT_ALGORITHM = "HS256"
ACCESS_EXPIRE_DAYS = 1     # access token — qisqa
REFRESH_EXPIRE_DAYS = 90   # refresh token — uzoq

# auto_error=False — token bo'lmasa o'zimiz tushunarli xato qaytaramiz
bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(user_id: int) -> str:
    """Qisqa muddatli access JWT token yaratadi."""
    expire = datetime.now(timezone.utc) + timedelta(days=ACCESS_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_refresh_token(user_id: int, db: Session) -> str:
    """Tasodifiy refresh token yaratadi, hash'ini DB'ga saqlaydi, XOM tokenni
    qaytaradi (faqat shu yerda ko'rinadi)."""
    raw = secrets.token_urlsafe(48)
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_EXPIRE_DAYS)
    db.add(RefreshToken(
        user_id=user_id,
        token_hash=_hash_token(raw),
        expires_at=expire,
    ))
    db.commit()
    return raw


def verify_refresh_token(raw: str, db: Session) -> Optional[int]:
    """Refresh token yaroqli bo'lsa user_id qaytaradi, aks holda None."""
    row = db.query(RefreshToken).filter(
        RefreshToken.token_hash == _hash_token(raw)
    ).first()
    if row is None:
        return None
    exp = row.expires_at
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp is None or exp < datetime.now(timezone.utc):
        db.delete(row)  # muddati tugagan — tozalaymiz
        db.commit()
        return None
    return row.user_id


def revoke_refresh_token(raw: str, db: Session) -> None:
    """Bitta refresh tokenni o'chiradi (logout)."""
    db.query(RefreshToken).filter(
        RefreshToken.token_hash == _hash_token(raw)
    ).delete()
    db.commit()


def revoke_all_refresh_tokens(user_id: int, db: Session) -> None:
    """Foydalanuvchining barcha refresh tokenlarini o'chiradi (hisob o'chirish)."""
    db.query(RefreshToken).filter(RefreshToken.user_id == user_id).delete()
    db.commit()


def _decode_token(token: str):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Token majburiy bo'lgan endpointlar uchun. Token yo'q/yaroqsiz bo'lsa 401."""
    if creds is None:
        raise HTTPException(status_code=401, detail="Avtorizatsiya talab qilinadi")

    payload = _decode_token(creds.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Token yaroqsiz yoki muddati tugagan")

    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if user is None:
        raise HTTPException(status_code=401, detail="Foydalanuvchi topilmadi")
    return user


def get_current_user_optional(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Token ixtiyoriy bo'lgan endpointlar uchun (bor bo'lsa user, yo'q bo'lsa None)."""
    if creds is None:
        return None
    payload = _decode_token(creds.credentials)
    if not payload or "sub" not in payload:
        return None
    return db.query(User).filter(User.id == int(payload["sub"])).first()


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    """Admin huquqi talab qilinadigan endpointlar uchun."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin huquqi kerak")
    return user
