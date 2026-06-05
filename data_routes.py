from typing import List, Optional
from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from sqlalchemy.orm import Session
from pydantic import BaseModel
from models import Book, Unit, Word
from database import get_db

data_router = APIRouter(
    prefix='/data'
)


def _reset_all_data(db: Session) -> None:
    """Barcha kitob/unit/so'zlarni o'chiradi VA ID hisoblagichni (sequence)
    qaytadan 1 dan boshlanadigan qiladi. Postgres va SQLite'da ham ishlaydi."""
    dialect = db.bind.dialect.name
    if dialect == 'postgresql':
        # CASCADE — FK'larni hisobga oladi, RESTART IDENTITY — id'ni 1 ga qaytaradi
        db.execute(text('TRUNCATE TABLE word, unit, book RESTART IDENTITY CASCADE'))
    else:
        # SQLite: bo'sh jadvalga yangi yozuv 1 dan boshlanadi (oddiy PK rowid).
        # AUTOINCREMENT ishlatilgan bo'lsa sqlite_sequence'ni ham tozalaymiz.
        db.query(Word).delete()
        db.query(Unit).delete()
        db.query(Book).delete()
        try:
            db.execute(text(
                "DELETE FROM sqlite_sequence WHERE name IN ('word', 'unit', 'book')"
            ))
        except Exception:
            pass  # sqlite_sequence jadvali yo'q — muammo emas
    db.commit()


# ---------- Import uchun sxemalar ----------
class ImportWord(BaseModel):
    word_en: str
    word_uz: str
    comment: Optional[str] = None
    definition: Optional[str] = ''
    phonetic: Optional[str] = ''
    example: Optional[str] = ''
    word_classes: Optional[str] = ''
    isFavorite: Optional[bool] = False


class ImportUnit(BaseModel):
    name: str
    history: Optional[str] = ''
    words: List[ImportWord] = []


class ImportBook(BaseModel):
    name: str
    units: List[ImportUnit] = []


class ImportPayload(BaseModel):
    mode: str = 'add'           # 'add' yoki 'replace'
    data: List[ImportBook] = []


# ---------- EXPORT ----------
@data_router.get('/export')
async def export_data(db: Session = Depends(get_db)):
    """Butun bazani JSON ierarxiya ko'rinishida qaytaradi (ID'larsiz)."""
    books = []
    for book in db.query(Book).order_by(Book.id).all():
        units = []
        for unit in db.query(Unit).filter(Unit.book_id == book.id).order_by(Unit.id).all():
            words = []
            for w in db.query(Word).filter(Word.unit_id == unit.id).order_by(Word.id).all():
                words.append({
                    'word_en': w.word_en,
                    'word_uz': w.word_uz,
                    'comment': w.comment,
                    'definition': w.definition,
                    'phonetic': w.phonetic,
                    'example': w.example,
                    'word_classes': w.word_classes,
                    'isFavorite': w.isFavorite,
                })
            units.append({'name': unit.name, 'history': unit.history, 'words': words})
        books.append({'name': book.name, 'units': units})

    summary = {
        'books': len(books),
        'units': sum(len(b['units']) for b in books),
        'words': sum(len(u['words']) for b in books for u in b['units']),
    }

    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': 'Eksport tayyor',
        'data': {'summary': summary, 'books': books},
    })


# ---------- IMPORT ----------
@data_router.post('/import')
async def import_data(payload: ImportPayload, db: Session = Depends(get_db)):
    """JSON ma'lumotni bazaga yozadi. mode='replace' bo'lsa avval tozalaydi."""
    if payload.mode == 'replace':
        _reset_all_data(db)

    books_added = units_added = words_added = 0

    for b in payload.data:
        new_book = Book(name=b.name)
        db.add(new_book)
        db.flush()  # new_book.id ni olish uchun
        books_added += 1

        for u in b.units:
            new_unit = Unit(name=u.name, history=u.history or '', book_id=new_book.id)
            db.add(new_unit)
            db.flush()
            units_added += 1

            for w in u.words:
                db.add(Word(
                    word_en=w.word_en,
                    word_uz=w.word_uz,
                    comment=w.comment,
                    definition=w.definition or '',
                    phonetic=w.phonetic or '',
                    example=w.example or '',
                    word_classes=w.word_classes or '',
                    isFavorite=bool(w.isFavorite),
                    unit_id=new_unit.id,
                ))
                words_added += 1

    db.commit()

    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': "Import muvaffaqiyatli yakunlandi ('%s' rejimi)" % payload.mode,
        'data': {
            'mode': payload.mode,
            'books_added': books_added,
            'units_added': units_added,
            'words_added': words_added,
        },
    })
