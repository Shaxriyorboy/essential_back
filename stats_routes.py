from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session
from models import Book, Unit, Word
from database import get_db

stats_router = APIRouter(
    prefix='/stats'
)


@stats_router.get('/')
async def get_stats(db: Session = Depends(get_db)):
    """Dashboard uchun umumiy statistika"""
    books_count = db.query(Book).count()
    units_count = db.query(Unit).count()
    words_count = db.query(Word).count()
    favorites_count = db.query(Word).filter(Word.isFavorite == True).count()

    # Har bir kitobdagi unit va so'zlar soni
    per_book = []
    for book in db.query(Book).all():
        unit_ids = [u.id for u in db.query(Unit).filter(Unit.book_id == book.id).all()]
        word_count = (
            db.query(Word).filter(Word.unit_id.in_(unit_ids)).count()
            if unit_ids else 0
        )
        per_book.append({
            'id': book.id,
            'name': book.name,
            'units': len(unit_ids),
            'words': word_count,
        })

    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': 'Hammasi yaxshi',
        'data': {
            'books': books_count,
            'units': units_count,
            'words': words_count,
            'favorites': favorites_count,
            'per_book': per_book,
        }
    })
