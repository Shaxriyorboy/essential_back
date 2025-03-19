from fastapi import APIRouter, status
from fastapi.encoders import jsonable_encoder
from schemes import BookModel
from models import Book
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