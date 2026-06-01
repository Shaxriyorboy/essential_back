from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder
from models import Book, Unit, Word
from database import session, engine

stats_router = APIRouter(
    prefix='/stats'
)

session = session(bind=engine)


@stats_router.get('/')
async def get_stats():
    """Dashboard uchun umumiy statistika"""
    books_count = session.query(Book).count()
    units_count = session.query(Unit).count()
    words_count = session.query(Word).count()
    favorites_count = session.query(Word).filter(Word.isFavorite == True).count()

    # Har bir kitobdagi unit va so'zlar soni
    per_book = []
    for book in session.query(Book).all():
        unit_ids = [u.id for u in session.query(Unit).filter(Unit.book_id == book.id).all()]
        word_count = (
            session.query(Word).filter(Word.unit_id.in_(unit_ids)).count()
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
