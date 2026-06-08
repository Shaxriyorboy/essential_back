from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Book, Unit, UnitCompletion, User

progress_router = APIRouter(
    prefix='/progress'
)


@progress_router.get('')
def get_progress(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Joriy foydalanuvchining tugatgan unit va kitoblari.

    MUHIM: yo'l `''` (= `/progress`) — frontend `/progress` so'raydi. Agar
    `'/'` ('/progress/') bo'lsa, server 307 redirect qiladi va `http` paketi
    redirect paytida `Authorization` header'ni yo'qotadi → 401. Aniq moslik
    redirect'ni va shu bug'ni yo'q qiladi."""

    App shu ro'yxatlar asosida unit/kitobga "tugatilgan" belgisini qo'yadi.
    """
    completed_unit_ids = [
        uc.unit_id
        for uc in db.query(UnitCompletion.unit_id)
        .filter(UnitCompletion.user_id == user.id)
        .all()
    ]
    completed_set = set(completed_unit_ids)

    # Har bir kitob uchun: barcha unitlari complete bo'lsa -> kitob complete
    completed_book_ids = []
    for book in db.query(Book).order_by(Book.id).all():
        unit_ids = [u.id for u in db.query(Unit.id).filter(Unit.book_id == book.id).all()]
        if unit_ids and all(uid in completed_set for uid in unit_ids):
            completed_book_ids.append(book.id)

    return jsonable_encoder({
        "success": True,
        "code": 200,
        "message": "Progress",
        "data": {
            "completed_unit_ids": completed_unit_ids,
            "completed_book_ids": completed_book_ids,
        },
    })
