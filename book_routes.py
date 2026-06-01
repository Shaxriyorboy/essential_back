from fastapi import APIRouter, status
from fastapi.encoders import jsonable_encoder
from schemes import BookModel
from models import Book, Unit, Word
from database import session,engine

book_router = APIRouter(
    prefix='/book'
)

session = session(bind=engine)

@book_router.get('/')
async def book_route():
    return {'message': 'bu sahifa kitoblar uchun asosiy'}

@book_router.post('/add-book',status_code=201)
async def add_book(book: BookModel):
    new_book = Book(
        name = book.name
    )
    session.add(new_book)
    session.commit()

    custom_data = {
        'success': True,
        'code': 201,
        'message': 'Yangi kitob qo\'shildi',
        'data': {
            'id': new_book.id,
            'name': new_book.name,
        }
    }
    return jsonable_encoder(custom_data)

@book_router.put('/edit-book/{id}',status_code=201)
async def edit_book(book: BookModel,id: int):
    book_old = session.query(Book).filter(Book.id==id).first()

    if book_old is None:
        return {
            'success': False,
            'code': 404,
            'message': 'Bunday idli kitob topilmadi',
            'data': None
        }

    book_old.name = book.name
    session.commit()

    custom_data = {
        'success': True,
        'code': 201,
        'message': 'Hammasi yaxshi',
    }
    return jsonable_encoder(custom_data)

@book_router.delete('/delete-book',status_code=202)
async def deleteBook(id: int):
    book = session.query(Book).filter(id == Book.id).first()

    if book is None:
        return {
            'success': False,
            'code': 404,
            'message': 'Bunday idli kitob topilmadi',
            'data': None
        }

    # Kitobga tegishli unitlar va so'zlarni ham o'chiramiz (cascade)
    unit_ids = [u.id for u in session.query(Unit).filter(Unit.book_id == book.id).all()]
    if unit_ids:
        session.query(Word).filter(Word.unit_id.in_(unit_ids)).delete(synchronize_session=False)
    session.query(Unit).filter(Unit.book_id == book.id).delete(synchronize_session=False)
    session.delete(book)
    session.commit()

    custom_data = {
        'success': True,
        'code': 201,
        'message': 'Muoffaqiyatli o\'chirldi',
    }
    return jsonable_encoder(custom_data)

@book_router.get('/all-book')
async def get_all_book():
    books = session.query(Book).all()

    custom_data = {
        'success': True,
        'code': 200,
        'message': 'Successully',
        'data': [
            {
                'id': book.id,
                'name': book.name
            }
            for book in books
        ]
    }
    return jsonable_encoder(custom_data)