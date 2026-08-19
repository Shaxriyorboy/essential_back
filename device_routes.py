import os
from datetime import datetime

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:  # pragma: no cover
    ZoneInfo = None

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Device, User, UserWord
from schemes import DeviceRegisterModel, DeviceUnregisterModel
import push

device_router = APIRouter(prefix='/devices')

# Cron har soat chaqiradi — push faqat shu mahalliy soat(lar)da yuboriladi.
DEFAULT_REMINDER_HOURS = {11, 16, 19}


def _due_reviews_count(db: Session, user_id: int, local_date: str) -> int:
    """Bugungi muddati kelgan takrorlashlar soni."""
    return (
        db.query(func.count(UserWord.id))
        .filter(UserWord.user_id == user_id,
                UserWord.due_date.isnot(None),
                UserWord.due_date <= local_date)
        .scalar()
    ) or 0


def _build_reminder(db: Session, user: User, local_date: str):
    """Foydalanuvchi HOLATIGA qarab eslatma matnini tuzadi.

    Qaytadi: (title, body, type) yoki None (bugun faol — eslatma shart emas).

    Aqlli tanlov (muhimlik bo'yicha):
      1. Streak xavf ostida (eng kuchli motivatsiya — yo'qotish qo'rquvi).
         Muzlatgich bo'lsa xabar yumshoqroq (streak baribir saqlanadi).
      2. Muddati kelgan takrorlash bor — aniq son bilan.
      3. Hech qanday streak/ish yo'q — yumshoq "boshlang" chaqirig'i.
    """
    if user.last_active_date == local_date:
        return None  # bugun allaqachon faol

    streak = user.current_streak or 0
    freezes = user.streak_freezes or 0

    if streak >= 1:
        title = f"🔥 {streak} kunlik seriya xavf ostida"
        if freezes > 0:
            body = ("Bugun mashq qilmasangiz muzlatgich sarflanadi. "
                    "Atigi 5 daqiqa — seriyangizni bejiz sarflamang!")
        else:
            body = ("Bugun mashq qilmasangiz seriyangiz uziladi. "
                    "Atigi 5 daqiqa bas!")
        return (title, body, "streak_reminder")

    due = _due_reviews_count(db, user.id, local_date)
    if due > 0:
        return (
            f"📚 {due} ta so'z takrorlashga tayyor",
            "Bir necha daqiqa mashq qilib xotirangizda mustahkamlang.",
            "review_due",
        )

    return (
        "Bugun o'rganishni boshlang ✨",
        "Bir necha yangi so'z sizni kutmoqda — 5 daqiqa yetarli!",
        "learn_new",
    )


@device_router.post('')
def register_device(
    body: DeviceRegisterModel,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """FCM qurilma tokenini ro'yxatdan o'tkazadi (login'dan keyin).

    Token allaqachon mavjud bo'lsa — egasi/platforma/zona yangilanadi
    (qurilmada boshqa akkaunt kirgan bo'lishi mumkin)."""
    token = (body.token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token bo'sh")

    device = db.query(Device).filter(Device.token == token).first()
    if device is None:
        device = Device(token=token)
        db.add(device)

    device.user_id = user.id
    device.platform = body.platform
    device.timezone = body.timezone
    db.commit()

    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': "Qurilma ro'yxatdan o'tkazildi",
        'data': None,
    })


@device_router.post('/unregister')
def unregister_device(
    body: DeviceUnregisterModel,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Chiqishda/hisob o'chirishda qurilma tokenini o'chiradi."""
    token = (body.token or "").strip()
    if token:
        db.query(Device).filter(Device.token == token).delete()
        db.commit()

    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': "Qurilma o'chirildi",
        'data': None,
    })


def _user_local_date_and_hour(tz_name):
    """Qurilma zonasi bo'yicha (sana "YYYY-MM-DD", soat int). Zona noto'g'ri bo'lsa None."""
    if not tz_name or ZoneInfo is None:
        return None
    try:
        now = datetime.now(ZoneInfo(tz_name))
    except Exception:
        return None
    return (now.strftime("%Y-%m-%d"), now.hour)


@device_router.post('/send-reminders')
def send_reminders(
    db: Session = Depends(get_db),
    x_cron_secret: str = Header(None),
    force: bool = Query(False, description="Soat tekshiruvisiz hammaga yuborish (test)"),
):
    """Streak eslatmalarini push qiladi (server cron chaqiradi).

    Render Cron Job'dan har soat chaqiriladi:
        POST /devices/send-reminders  (header: X-Cron-Secret: <CRON_SECRET>)

    Faqat (a) qurilmaning mahalliy soati eslatma soat(lar)ida bo'lgan va
    (b) foydalanuvchi bugun hali mashq qilmagan qurilmalarga yuboriladi.
    Bitta foydalanuvchiga bir chaqiruvda faqat bir marta yuboriladi.
    """
    secret = os.environ.get("CRON_SECRET")
    if not secret or x_cron_secret != secret:
        raise HTTPException(status_code=401, detail="Cron secret yaroqsiz")

    if not push.is_configured():
        raise HTTPException(
            status_code=503,
            detail="FCM sozlanmagan (FIREBASE_SERVICE_ACCOUNT yo'q)",
        )

    sent = 0
    skipped = 0
    pruned = 0
    notified_users = set()

    devices = db.query(Device).filter(Device.user_id.isnot(None)).all()
    for device in devices:
        local = _user_local_date_and_hour(device.timezone)
        if local is None:
            skipped += 1
            continue
        local_date, local_hour = local

        if not force and local_hour not in DEFAULT_REMINDER_HOURS:
            skipped += 1
            continue

        # Bitta foydalanuvchiga bir marta (bir nechta qurilmasi bo'lsa ham)
        if device.user_id in notified_users:
            continue

        user = db.query(User).filter(User.id == device.user_id).first()
        if user is None:
            continue

        # Holatga qarab aqlli eslatma tuzamiz. None — bugun faol, shart emas.
        reminder = _build_reminder(db, user, local_date)
        if reminder is None:
            skipped += 1
            continue
        title, body, rtype = reminder

        ok, unregistered = push.send_to_token(
            device.token, title, body, data={"type": rtype}
        )
        if ok:
            sent += 1
            notified_users.add(device.user_id)
        elif unregistered:
            db.delete(device)
            pruned += 1

    if pruned:
        db.commit()

    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': "Eslatmalar yuborildi",
        'data': {"sent": sent, "skipped": skipped, "pruned": pruned},
    })
