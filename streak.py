from datetime import date, timedelta

from sqlalchemy.orm import Session

from models import StreakDay, StreakFreezeLog, User

# Kunni "yopish" uchun minimal foiz (Bosqich 1 qarori)
QUIZ_PASS_PERCENT = 80
AI_PASS_PERCENT = 70

# --- Streak muzlatgichi (streak freeze) ------------------------------------
# Muzlatgich o'tkazib yuborilgan kunni "yopib" streakni saqlaydi. Reklama
# (rewarded ad) ko'rib topiladi.
#
# Nega kerak: 30 kunlik streakni bitta kun o'tkazib yuborgani uchun yo'qotgan
# foydalanuvchi JAHL bilan ilovani tashlaydi. Muzlatgich shu "g'azabli churn"ни
# kamaytiradi va reklama ko'rishga tabiiy sabab beradi (daromad + retention).
MAX_FREEZES_HELD = 3        # bir vaqtda ushlab turish mumkin bo'lgan eng ko'pi
EARN_PER_DAY_CAP = 1        # kuniga nechta topish mumkin (buzuq client himoyasi)
# Ko'prik: eng ko'pi bilan shuncha ketma-ket o'tkazilgan kunni yopadi. Katta
# tanaffusni (masalan 30 kun) muzlatgich bilan "yopish" mantiqsiz — streak
# baribir uzilishi kerak.
MAX_FREEZE_BRIDGE_DAYS = 2

# Kunni yopa oladigan manbalar.
#   "quiz"   — unit quizi (faqat YANGI unit tugatilganda)
#   "ai"     — AI speaking partnyor bilan suhbat
#   "review" — kunlik SRS takrorlash sessiyasi
#
# MUHIM: "review" aynan STREAK DEVORINI yo'q qilish uchun qo'shildi. Avval kun
# faqat yangi unit tugatilganda yopilardi — 180 ta unit tugagach eng sodiq
# foydalanuvchi streakini boshqa hech qachon davom ettira olmasdi. Endi kunlik
# takrorlash sessiyasi ham kunni yopadi, ya'ni streak cheksiz oziqlanadi.
STREAK_SOURCES = ("quiz", "ai", "review")


def _safe_date(s: str):
    """ "YYYY-MM-DD" -> date. Noto'g'ri bo'lsa None."""
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _streak_dict(user: User, increased: bool, freeze_used: bool = False) -> dict:
    return {
        "current_streak": user.current_streak or 0,
        "longest_streak": user.longest_streak or 0,
        "streak_freezes": user.streak_freezes or 0,
        "last_active_date": user.last_active_date,
        "increased": increased,
        # True — bu kunni yopishda muzlatgich ishlatilib, streak SAQLANDI
        "freeze_used": freeze_used,
    }


def close_day(db: Session, user: User, local_date: str, source: str, score: int) -> dict:
    """Foydalanuvchining `local_date` kunini yopadi va streakni yangilaydi.

    Kun client'ning O'Z mahalliy sanasi bo'yicha hisoblanadi (vaqt zonasi
    har kimga mos). Kunni quiz YOKI ai bittasi yopadi — agar shu kun allaqachon
    yopilgan bo'lsa, takror oshirilmaydi.

    O'tkazib yuborilgan kun(lar) bo'lsa va muzlatgich yetarli bo'lsa —
    tanaffus muzlatgich bilan "yopiladi" va streak uzilmaydi
    (MAX_FREEZE_BRIDGE_DAYS gacha).

    Qaytadi: {current_streak, longest_streak, streak_freezes,
              last_active_date, increased, freeze_used}
    """
    today = _safe_date(local_date)
    if today is None:
        # Sanani o'qib bo'lmadi — streakni o'zgartirmaymiz
        return _streak_dict(user, increased=False)

    increased = False
    freeze_used = False

    # Bu kun allaqachon yopilganmi?
    existing = (
        db.query(StreakDay)
        .filter(StreakDay.user_id == user.id, StreakDay.local_date == local_date)
        .first()
    )

    if existing is None:
        db.add(StreakDay(
            user_id=user.id,
            local_date=local_date,
            source=source,
            score=score,
        ))

        last = _safe_date(user.last_active_date) if user.last_active_date else None

        if user.last_active_date == local_date:
            # Xavfsizlik: yozuv yo'q edi, lekin bugun faol deb belgilangan
            increased = False
        elif last is not None and last == today - timedelta(days=1):
            # Kecha ham faol bo'lgan — streak davom etadi
            user.current_streak = (user.current_streak or 0) + 1
            increased = True
        elif last is not None and today - timedelta(days=1) > last:
            # Bir yoki bir necha kun o'tkazib yuborilgan. Muzlatgich yetarli
            # bo'lsa — o'sha kunlarni "yopib" streakni saqlaymiz.
            missed = (today - last).days - 1
            freezes = user.streak_freezes or 0
            if 1 <= missed <= MAX_FREEZE_BRIDGE_DAYS and freezes >= missed:
                user.streak_freezes = freezes - missed
                user.current_streak = (user.current_streak or 0) + 1
                increased = True
                freeze_used = True
            else:
                # Muzlatgich yetmadi (yoki tanaffus juda katta) — uzildi
                user.current_streak = 1
                increased = True
        else:
            # Birinchi marta yoki g'alati sana — yangidan boshlanadi
            user.current_streak = 1
            increased = True

        user.last_active_date = local_date
        if (user.current_streak or 0) > (user.longest_streak or 0):
            user.longest_streak = user.current_streak

        db.commit()
        db.refresh(user)

    return _streak_dict(user, increased, freeze_used)


def earn_freeze(db: Session, user: User, local_date: str) -> dict:
    """Reklama (rewarded ad) ko'rilgach bitta muzlatgich beradi.

    Cheklovlar (buzuq client himoyasi):
      - bir vaqtda MAX_FREEZES_HELD tadan ko'p ushlab bo'lmaydi
      - kuniga EARN_PER_DAY_CAP tadan ko'p topib bo'lmaydi

    Qaytadi: {ok, reason, streak_freezes, max_freezes, earned_today}.
    `ok=False` bo'lsa `reason` sababi ("max_held" | "daily_cap").
    """
    held = user.streak_freezes or 0

    earned_today = (
        db.query(StreakFreezeLog)
        .filter(StreakFreezeLog.user_id == user.id,
                StreakFreezeLog.local_date == local_date)
        .count()
    )

    def result(ok: bool, reason: str = ""):
        return {
            "ok": ok,
            "reason": reason,
            "streak_freezes": user.streak_freezes or 0,
            "max_freezes": MAX_FREEZES_HELD,
            "earned_today": earned_today + (1 if ok else 0),
        }

    if held >= MAX_FREEZES_HELD:
        return result(False, "max_held")
    if earned_today >= EARN_PER_DAY_CAP:
        return result(False, "daily_cap")

    user.streak_freezes = held + 1
    db.add(StreakFreezeLog(user_id=user.id, local_date=local_date,
                           source="rewarded_ad"))
    db.commit()
    db.refresh(user)
    return result(True)
