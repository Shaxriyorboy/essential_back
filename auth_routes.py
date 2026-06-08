import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from database import get_db
from models import User, Device, StreakDay, UnitCompletion
from schemes import GoogleAuthModel
from auth import create_access_token, get_current_user

auth_router = APIRouter(prefix='/auth')

# Bir nechta client id (Android / iOS / Web) vergul bilan berilishi mumkin.
GOOGLE_CLIENT_IDS = [
    c.strip()
    for c in os.environ.get("GOOGLE_CLIENT_ID", "").split(",")
    if c.strip()
]


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
    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': 'Muvaffaqiyatli kirildi',
        'data': {
            'token': token,
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
    db.delete(user)
    db.commit()

    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': "Hisob o'chirildi",
        'data': None,
    })
