from datetime import date, timedelta

from sqlalchemy.orm import Session

from models import StreakDay, User

# Kunni "yopish" uchun minimal foiz (Bosqich 1 qarori)
QUIZ_PASS_PERCENT = 80
AI_PASS_PERCENT = 70


def _safe_date(s: str):
    """ "YYYY-MM-DD" -> date. Noto'g'ri bo'lsa None."""
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def close_day(db: Session, user: User, local_date: str, source: str, score: int) -> dict:
    """Foydalanuvchining `local_date` kunini yopadi va streakni yangilaydi.

    Kun client'ning O'Z mahalliy sanasi bo'yicha hisoblanadi (vaqt zonasi
    har kimga mos). Kunni quiz YOKI ai bittasi yopadi — agar shu kun allaqachon
    yopilgan bo'lsa, takror oshirilmaydi.

    Qaytadi: {current_streak, longest_streak, last_active_date, increased}
    """
    today = _safe_date(local_date)
    if today is None:
        # Sanani o'qib bo'lmadi — streakni o'zgartirmaymiz
        return {
            "current_streak": user.current_streak or 0,
            "longest_streak": user.longest_streak or 0,
            "last_active_date": user.last_active_date,
            "increased": False,
        }

    increased = False

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
        else:
            # Streak uzilgan yoki birinchi marta — yangidan boshlanadi
            user.current_streak = 1
            increased = True

        user.last_active_date = local_date
        if (user.current_streak or 0) > (user.longest_streak or 0):
            user.longest_streak = user.current_streak

        db.commit()
        db.refresh(user)

    return {
        "current_streak": user.current_streak or 0,
        "longest_streak": user.longest_streak or 0,
        "last_active_date": user.last_active_date,
        "increased": increased,
    }
