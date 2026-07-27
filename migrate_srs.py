"""Bir martalik migratsiya: mavjud foydalanuvchilarni SRS'ga ko'chirish.

Quizdan o'tgan (tugatilgan) unitlardagi so'zlar 0-DARAJADAN EMAS, 1-DARAJADAN
boshlanadi. Hammasini noldan boshlash mavjud foydalanuvchiga haqorat — u so'zlarni
allaqachon o'rgangan.

MUHIM: `due_date` sanalari 14 kunga YOYILADI. Aks holda 50 ta unit tugatgan
foydalanuvchiga bir kunda 1000 ta takrorlash tushadi va u ilovani o'sha kuni
o'chiradi. Bu SRS joriy qilishdagi eng ko'p uchraydigan xato.

Ishga tushirish (bir marta, deploy'dan keyin):
    python migrate_srs.py            # haqiqiy migratsiya
    python migrate_srs.py --dry-run  # faqat nechta yozuv qo'shilishini ko'rsatadi
"""
import random
import sys
from datetime import date, timedelta

from sqlalchemy.orm import Session

from database import SessionLocal
from models import UnitCompletion, UserWord, Word
from srs import EASE_START

SPREAD_DAYS = 14   # due sanalar shuncha kunga yoyiladi
SEED_STAGE = 1     # "ma'noni eslash" darajasi
SEED_STEP = 1      # INTERVALS[1] = 3 kun


def migrate(db: Session, dry_run: bool = False) -> dict:
    today = date.today()

    # Tugatilgan unitlardagi (user, word) juftliklari
    pairs = (
        db.query(UnitCompletion.user_id, Word.id)
        .join(Word, Word.unit_id == UnitCompletion.unit_id)
        .all()
    )

    # Allaqachon mavjud yozuvlar — takror qo'shmaymiz (idempotent)
    existing = {
        (uw.user_id, uw.word_id)
        for uw in db.query(UserWord.user_id, UserWord.word_id).all()
    }

    to_add = [(u, w) for (u, w) in pairs if (u, w) not in existing]

    if dry_run:
        return {
            "candidates": len(pairs),
            "already_present": len(pairs) - len(to_add),
            "would_insert": len(to_add),
        }

    rng = random.Random(42)  # takrorlanadigan natija
    for user_id, word_id in to_add:
        offset = rng.randint(0, SPREAD_DAYS)
        db.add(UserWord(
            user_id=user_id,
            word_id=word_id,
            stage=SEED_STAGE,
            stage_reps=0,
            step=SEED_STEP,
            ease=EASE_START,
            interval_days=3,
            due_date=(today + timedelta(days=offset)).isoformat(),
            reps=1,
            lapses=0,
            active_uses=0,
        ))

    db.commit()
    return {
        "candidates": len(pairs),
        "already_present": len(pairs) - len(to_add),
        "inserted": len(to_add),
    }


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    db = SessionLocal()
    try:
        result = migrate(db, dry_run=dry)
        print("DRY RUN — hech narsa yozilmadi" if dry else "Migratsiya tugadi")
        for key, value in result.items():
            print(f"  {key}: {value}")
    finally:
        db.close()
