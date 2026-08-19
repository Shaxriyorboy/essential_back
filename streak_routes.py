"""Streak va streak-muzlatgichi (streak freeze) endpointlari.

    GET  /streak              — joriy streak + muzlatgichlar soni
    POST /streak/earn-freeze  — reklama ko'rilgach bitta muzlatgich beradi

MUHIM (yo'l nomlari): `''` ishlatilgan, `'/'` emas — aks holda FastAPI 307
redirect qiladi va `Authorization` header yo'qoladi -> 401
(`review_routes.py` dagi izohga qarang).

XAVFSIZLIK: `earn-freeze` MVP darajasida — kod client'ning "reklama ko'rildi"
so'roviga ishonadi, lekin kunlik cheklov (EARN_PER_DAY_CAP) va maksimum ushlash
(MAX_FREEZES_HELD) bilan himoyalangan. Ishlab chiqarishda AdMob Server-Side
Verification (SSV) callback'i orqali tasdiqlash tavsiya etiladi.
"""
from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy.orm import Session

import streak
from auth import get_current_user
from database import get_db
from models import User

streak_router = APIRouter(prefix='/streak')


class EarnFreezeModel(BaseModel):
    # Client mahalliy sanasi "YYYY-MM-DD" (kunlik cheklov shunga bog'lanadi).
    local_date: str


def _ok(message: str, data):
    return jsonable_encoder({
        "success": True,
        "code": 200,
        "message": message,
        "data": data,
    })


@streak_router.get('')
def get_streak(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Joriy streak holati — bosh ekran va profil uchun."""
    return _ok("Streak", {
        "current_streak": user.current_streak or 0,
        "longest_streak": user.longest_streak or 0,
        "streak_freezes": user.streak_freezes or 0,
        "max_freezes": streak.MAX_FREEZES_HELD,
        "last_active_date": user.last_active_date,
    })


@streak_router.post('/earn-freeze')
def earn_freeze(
    body: EarnFreezeModel,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Reklama (rewarded ad) ko'rilgach bitta muzlatgich beradi.

    Cheklovga uchrasa `ok=False` va sabab qaytadi (HTTP 200 — bu xato emas,
    kutilgan holat). Client `ok` va `reason` ga qarab xabar ko'rsatadi.
    """
    res = streak.earn_freeze(db, user, body.local_date)
    message = "Muzlatgich qo'shildi" if res["ok"] else "Cheklovga yetildi"
    return _ok(message, res)
