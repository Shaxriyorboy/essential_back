from fastapi import APIRouter, status
from fastapi.encoders import jsonable_encoder
from schemes import BaseModel,UnitModel
from models import Book,Unit,Word
from database import engine,session

unit_router = APIRouter(
    prefix='/unit'
)

session = session(bind=engine)

@unit_router.get('/')
async def get_unit():
    return {"message": "Bu sahifa unitlar uchun"} 

@unit_router.post('/add-unit',status_code=201)
async def add_book(unit: UnitModel):
    book = session.query(Book).filter(Book.id==unit.book_id).first()
    if book is None:
        return {
            'success':False,
            'code': 403,
            'message': 'Bunday idli kitob topilmadi',
            'data': None
        }
    
    new_unit = Unit(
        name = unit.name,
        history = unit.history,
        book_id = unit.book_id,
    )
    session.add(new_unit)
    session.commit()

    return {
        'success':True,
        'code': 201,
        'message':'Unit mofaqiyatli qoshildi',
        'data': {
            'id': new_unit.id,
            'name': new_unit.name,
            'history': new_unit.history,
            'book_id': new_unit.book_id
        
        }
    }

@unit_router.get('/{book_id}')
async def get_single_unit(book_id: int):

    book = session.query(Book).filter(Book.id == book_id).first()
    if book is None:
        return {
            'success':False,
            'code': 403,
            'message': 'Bunday idli kitob topilmadi',
            'data': None
        }

    units = session.query(Unit).filter(Unit.book_id==book_id).all()
    custom_data = {
        'success':True,
        'code': 201,
        'message':'Unit mofaqiyatli qoshildi',
        'data': [
            {
            'id': unit.id,
            'name': unit.name,
            'history': unit.history,
            'book_id': unit.book_id
        }
        for unit in units
        ]
    }
    return jsonable_encoder(custom_data)


@unit_router.put('/edit-unit/{id}', status_code=200)
async def edit_unit(id: int, unit: UnitModel):
    unit_old = session.query(Unit).filter(Unit.id == id).first()
    if unit_old is None:
        return {
            'success': False,
            'code': 404,
            'message': 'Bunday idli unit topilmadi',
            'data': None
        }

    unit_old.name = unit.name
    unit_old.history = unit.history
    if unit.book_id is not None:
        unit_old.book_id = unit.book_id
    session.commit()

    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': 'Unit muvaffaqiyatli tahrirlandi',
        'data': {
            'id': unit_old.id,
            'name': unit_old.name,
            'history': unit_old.history,
            'book_id': unit_old.book_id
        }
    })


@unit_router.delete('/delete-unit/{id}', status_code=200)
async def delete_unit(id: int):
    unit = session.query(Unit).filter(Unit.id == id).first()
    if unit is None:
        return {
            'success': False,
            'code': 404,
            'message': 'Bunday idli unit topilmadi',
            'data': None
        }

    # Unitga tegishli barcha so'zlarni ham o'chiramiz (cascade)
    session.query(Word).filter(Word.unit_id == id).delete()
    session.delete(unit)
    session.commit()

    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': 'Unit va unga tegishli so\'zlar o\'chirildi',
        'data': None
    })

