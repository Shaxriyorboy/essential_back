from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session
from schemes import UnitModel
from models import Book, Unit, Word
from database import get_db

unit_router = APIRouter(
    prefix='/unit'
)


@unit_router.get('/')
async def get_unit():
    return {"message": "Bu sahifa unitlar uchun"}


@unit_router.post('/add-unit', status_code=201)
async def add_unit(unit: UnitModel, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == unit.book_id).first()
    if book is None:
        return {
            'success': False,
            'code': 403,
            'message': 'Bunday idli kitob topilmadi',
            'data': None
        }

    new_unit = Unit(
        name=unit.name,
        history=unit.history,
        book_id=unit.book_id,
    )
    db.add(new_unit)
    db.commit()

    return {
        'success': True,
        'code': 201,
        'message': 'Unit mofaqiyatli qoshildi',
        'data': {
            'id': new_unit.id,
            'name': new_unit.name,
            'history': new_unit.history,
            'book_id': new_unit.book_id
        }
    }


@unit_router.get('/{book_id}')
async def get_single_unit(book_id: int, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == book_id).first()
    if book is None:
        return {
            'success': False,
            'code': 403,
            'message': 'Bunday idli kitob topilmadi',
            'data': None
        }

    units = db.query(Unit).filter(Unit.book_id == book_id).order_by(Unit.id).all()
    custom_data = {
        'success': True,
        'code': 201,
        'message': 'Unit mofaqiyatli qoshildi',
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
async def edit_unit(id: int, unit: UnitModel, db: Session = Depends(get_db)):
    unit_old = db.query(Unit).filter(Unit.id == id).first()
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
    db.commit()

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
async def delete_unit(id: int, db: Session = Depends(get_db)):
    unit = db.query(Unit).filter(Unit.id == id).first()
    if unit is None:
        return {
            'success': False,
            'code': 404,
            'message': 'Bunday idli unit topilmadi',
            'data': None
        }

    # Unitga tegishli barcha so'zlarni ham o'chiramiz (cascade)
    db.query(Word).filter(Word.unit_id == id).delete()
    db.delete(unit)
    db.commit()

    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': 'Unit va unga tegishli so\'zlar o\'chirildi',
        'data': None
    })
