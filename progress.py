"""Unit/Book tugatish (completion) mantiqi.

Qoidalar (kelishilgan):
- Unit quizi >=80% bo'lsa va unit hali tugatilmagan bo'lsa -> unit "complete"
  qilinadi VA shu safar streak beriladi.
- Allaqachon tugatilgan unitni qayta ishlasa -> hech narsa (streak ham yo'q).
- Kitob tugatilgani alohida saqlanmaydi: kitobdagi BARCHA unit complete bo'lsa,
  kitob ham complete deb hisoblanadi.
"""
from sqlalchemy.orm import Session

from models import Unit, UnitCompletion


def is_unit_completed(db: Session, user_id: int, unit_id: int) -> bool:
    return (
        db.query(UnitCompletion)
        .filter(UnitCompletion.user_id == user_id, UnitCompletion.unit_id == unit_id)
        .first()
        is not None
    )


def is_book_completed(db: Session, user_id: int, book_id: int) -> bool:
    """Kitobdagi barcha unit shu user uchun complete bo'lsa True."""
    total = db.query(Unit).filter(Unit.book_id == book_id).count()
    if total == 0:
        return False
    done = (
        db.query(UnitCompletion)
        .join(Unit, Unit.id == UnitCompletion.unit_id)
        .filter(Unit.book_id == book_id, UnitCompletion.user_id == user_id)
        .count()
    )
    return done >= total


def complete_unit_if_new(db: Session, user_id: int, unit_id: int, score: int) -> dict:
    """Unitni (agar yangi bo'lsa) complete qiladi.

    Qaytadi: {newly_completed, already_completed, book_id, book_completed}.
    Bazaga commit QILMAYDI — chaqiruvchi commit qiladi (streak bilan birga).
    """
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if unit is None:
        return {
            "newly_completed": False,
            "already_completed": False,
            "book_id": None,
            "book_completed": False,
        }

    if is_unit_completed(db, user_id, unit_id):
        return {
            "newly_completed": False,
            "already_completed": True,
            "book_id": unit.book_id,
            "book_completed": is_book_completed(db, user_id, unit.book_id),
        }

    db.add(UnitCompletion(user_id=user_id, unit_id=unit_id, score=score))
    db.flush()  # is_book_completed yangi yozuvni hisobga olishi uchun

    return {
        "newly_completed": True,
        "already_completed": False,
        "book_id": unit.book_id,
        "book_completed": is_book_completed(db, user_id, unit.book_id),
    }
