import hashlib
import os

import jwt
from jwt import PyJWKClient
from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from database import get_db
from models import User, Device, StreakDay, UnitCompletion, UserFavorite, WordComment
from schemes import GoogleAuthModel, AppleAuthModel, RefreshModel
from auth import (
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
    revoke_refresh_token,
    revoke_all_refresh_tokens,
    get_current_user,
)

auth_router = APIRouter(prefix='/auth')

# Bir nechta client id (Android / iOS / Web) vergul bilan berilishi mumkin.
GOOGLE_CLIENT_IDS = [
    c.strip()
    for c in os.environ.get("GOOGLE_CLIENT_ID", "").split(",")
    if c.strip()
]

# Apple Sign-In. `aud` — iOS app'ning bundle id'si (yoki Service ID).
# Vergul bilan bir nechta berilishi mumkin. Default — app bundle id.
APPLE_ISSUER = "https://appleid.apple.com"
APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"
APPLE_CLIENT_IDS = [
    c.strip()
    for c in os.environ.get("APPLE_CLIENT_ID", "essential.words.ai").split(",")
    if c.strip()
]
# Apple'ning public kalitlarini olib keshlaydigan client (JWKS).
_apple_jwk_client = PyJWKClient(APPLE_KEYS_URL)


def _user_dict(user: User) -> dict:
    return {
        'id': user.id,
        'email': user.email,
        'name': user.name,
        'picture': user.picture,
        'is_admin': user.is_admin,
        'current_streak': user.current_streak,
        'longest_streak': user.longest_streak,
        'last_active_date': user.last_active_date,
    }


@auth_router.post('/google')
async def google_login(body: GoogleAuthModel, db: Session = Depends(get_db)):
    """Flutter Google Sign-In'dan olingan id_token'ni tekshiradi,
    foydalanuvchini topadi/yaratadi va o'z JWT tokenimizni qaytaradi."""
    if not GOOGLE_CLIENT_IDS:
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID sozlanmagan")

    # Imzo va issuer'ni tekshiramiz (audience'ni o'zimiz quyida tekshiramiz —
    # shunda bir nechta client id'ni qo'llab-quvvatlay olamiz).
    try:
        idinfo = google_id_token.verify_oauth2_token(
            body.id_token, google_requests.Request()
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Google token yaroqsiz")

    if idinfo.get("aud") not in GOOGLE_CLIENT_IDS:
        raise HTTPException(status_code=401, detail="Token audience mos kelmadi")

    google_sub = idinfo["sub"]
    email = idinfo.get("email")
    name = idinfo.get("name")
    picture = idinfo.get("picture")

    # Avval google_sub bo'yicha, bo'lmasa email bo'yicha qidiramiz
    user = db.query(User).filter(User.google_sub == google_sub).first()
    if user is None and email:
        user = db.query(User).filter(User.email == email).first()

    if user is None:
        user = User(
            google_sub=google_sub,
            email=email,
            name=name,
            picture=picture,
            auth_provider="google",
        )
        db.add(user)
    else:
        # Profil ma'lumotlarini yangilab turamiz
        user.google_sub = user.google_sub or google_sub
        if email:
            user.email = email
        if name:
            user.name = name
        if picture:
            user.picture = picture

    db.commit()
    db.refresh(user)

    token = create_access_token(user.id)
    refresh = create_refresh_token(user.id, db)
    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': 'Muvaffaqiyatli kirildi',
        'data': {
            'token': token,
            'refresh_token': refresh,
            'user': _user_dict(user),
        }
    })


@auth_router.post('/apple')
async def apple_login(body: AppleAuthModel, db: Session = Depends(get_db)):
    """Apple Sign-In'dan olingan identityToken'ni tekshiradi, foydalanuvchini
    topadi/yaratadi va o'z JWT tokenimizni qaytaradi.

    Apple ism va email'ni FAQAT birinchi kirishda beradi — client ularni
    `name`/`email` orqali uzatadi, biz birinchi marta saqlab qolamiz."""
    # 1) Apple imzosini va da'volarni tekshiramiz (RS256, JWKS orqali).
    try:
        signing_key = _apple_jwk_client.get_signing_key_from_jwt(body.identity_token)
        claims = jwt.decode(
            body.identity_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=APPLE_CLIENT_IDS,
            issuer=APPLE_ISSUER,
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Apple token yaroqsiz")

    # 2) Nonce tekshiruvi (agar client yuborgan bo'lsa) — replay'dan himoya.
    if body.raw_nonce and claims.get("nonce"):
        expected = hashlib.sha256(body.raw_nonce.encode("utf-8")).hexdigest()
        if claims.get("nonce") != expected:
            raise HTTPException(status_code=401, detail="Nonce mos kelmadi")

    apple_sub = claims.get("sub")
    if not apple_sub:
        raise HTTPException(status_code=401, detail="Apple token to'liq emas")

    # Email token ichida bo'lishi mumkin; bo'lmasa client uzatganini olamiz.
    email = claims.get("email") or body.email
    name = body.name

    # 3) Avval apple_sub bo'yicha, bo'lmasa email bo'yicha qidiramiz.
    user = db.query(User).filter(User.apple_sub == apple_sub).first()
    if user is None and email:
        user = db.query(User).filter(User.email == email).first()

    if user is None:
        user = User(
            apple_sub=apple_sub,
            email=email,
            name=name,
            auth_provider="apple",
        )
        db.add(user)
    else:
        user.apple_sub = user.apple_sub or apple_sub
        # Email/ism faqat bo'sh bo'lsa to'ldiramiz (Apple keyingi kirishlarda bermaydi).
        if email and not user.email:
            user.email = email
        if name and not user.name:
            user.name = name

    db.commit()
    db.refresh(user)

    token = create_access_token(user.id)
    refresh = create_refresh_token(user.id, db)
    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': 'Muvaffaqiyatli kirildi',
        'data': {
            'token': token,
            'refresh_token': refresh,
            'user': _user_dict(user),
        }
    })


@auth_router.get('/me')
async def get_me(user: User = Depends(get_current_user)):
    """Joriy foydalanuvchi ma'lumotlari (token kerak)."""
    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': 'Hammasi yaxshi',
        'data': _user_dict(user),
    })


@auth_router.post('/refresh')
def refresh(body: RefreshModel, db: Session = Depends(get_db)):
    """Refresh token orqali yangi access token beradi. Refresh token o'zgarmaydi
    (rotatsiya yo'q). Yaroqsiz/tugagan bo'lsa 401 — client qayta login qiladi."""
    user_id = verify_refresh_token(body.refresh_token, db)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Refresh token yaroqsiz")
    token = create_access_token(user_id)
    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': 'Token yangilandi',
        'data': {'token': token},
    })


@auth_router.post('/logout')
def logout(body: RefreshModel, db: Session = Depends(get_db)):
    """Chiqish — refresh tokenni serverdan o'chiradi (bekor qiladi).
    Token bo'lmasa ham 200 (idempotent)."""
    revoke_refresh_token(body.refresh_token, db)
    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': 'Chiqildi',
        'data': None,
    })


# Hisobni o'chirish — frontend `DELETE /account` chaqiradi (shu sababli alohida
# router, `/auth` prefiksisiz).
account_router = APIRouter(prefix='/account')


@account_router.delete('')
def delete_account(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Joriy foydalanuvchini va unga bog'liq barcha ma'lumotlarni o'chiradi.

    Bu amalni qaytarib bo'lmaydi: profil, streak kunlari, unit tugatishlari
    va push qurilmalari butunlay o'chadi."""
    db.query(Device).filter(Device.user_id == user.id).delete()
    db.query(StreakDay).filter(StreakDay.user_id == user.id).delete()
    db.query(UnitCompletion).filter(UnitCompletion.user_id == user.id).delete()
    db.query(UserFavorite).filter(UserFavorite.user_id == user.id).delete()
    db.query(WordComment).filter(WordComment.user_id == user.id).delete()
    revoke_all_refresh_tokens(user.id, db)
    db.delete(user)
    db.commit()

    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': "Hisob o'chirildi",
        'data': None,
    })
