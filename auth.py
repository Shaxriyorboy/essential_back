import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from database import get_db
from models import User

# JWT sozlamalari. Maxfiy kalit env'dan olinadi (Render'ga JWT_SECRET qo'shing).
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 30  # mobil ilova uchun uzoq muddat

# auto_error=False — token bo'lmasa o'zimiz tushunarli xato qaytaramiz
bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(user_id: int) -> str:
    """Foydalanuvchi uchun JWT token yaratadi."""
    expire = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


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
