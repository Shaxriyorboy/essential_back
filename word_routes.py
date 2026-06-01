from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session
from schemes import WordModel
from models import Word, Unit
from database import get_db

word_router = APIRouter(
    prefix='/word'
)


@word_router.post('/add-word')
async def add_new_word(word: WordModel, db: Session = Depends(get_db)):
    unit = db.query(Unit).filter(Unit.id == word.unit_id).first()
    if unit is None:
        return {
            'success': False,
            'code': 403,
            'message': 'Bunday idli kitob topilmadi',
            'data': None
        }

    new_word = Word(
        word_en=word.word_en,
        word_uz=word.word_uz,
        comment=word.comment,
        definition=word.definition,
        phonetic=word.phonetic,
        example=word.example,
        word_classes=word.word_classes,
        isFavorite=word.isFavorite,
        unit_id=word.unit_id
    )

    db.add(new_word)
    db.commit()

    custom_data = {
        'success': True,
        'code': 201,
        'message': 'Hammasi yaxshi',
        'data': {
            'id': new_word.id,
            "word_en": new_word.word_en,
            'word_uz': new_word.word_uz,
            'comment': new_word.comment,
            'definition': new_word.definition,
            'phonetic': new_word.phonetic,
            'example': new_word.example,
            'word_classes': new_word.word_classes,
            'isFavorite': new_word.isFavorite,
            'unit_id': new_word.unit_id
        }
    }

    return jsonable_encoder(custom_data)


@word_router.delete('/delete-word')
async def delete_word(id: int, db: Session = Depends(get_db)):
    word = db.query(Word).filter(Word.id == id).first()

    if word is None:
        return {
            'success': False,
            'code': 403,
            'message': 'Bunday idli kitob topilmadi',
            'data': None
        }

    db.delete(word)
    db.commit()

    custom_data = {
        'success': True,
        'code': 202,
        'message': 'Muoffaqiyali o\'chilirdi',
    }

    return jsonable_encoder(custom_data)


@word_router.get('/favorite-words', status_code=200)
async def get_favorite_words(db: Session = Depends(get_db)):
    words = db.query(Word).filter(Word.isFavorite == True).all()

    custom_data = {
        'success': True,
        'code': 200,
        'message': 'Hammasi yaxshi',
        'data': [
            {
                'id': word.id,
                "word_en": word.word_en,
                'word_uz': word.word_uz,
                'comment': word.comment,
                'definition': word.definition,
                'phonetic': word.phonetic,
                'example': word.example,
                'word_classes': word.word_classes,
                'isFavorite': word.isFavorite,
                'unit_id': word.unit_id
            }
            for word in words
        ]
    }
    return jsonable_encoder(custom_data)


@word_router.get('/{unit_id}', status_code=200)
async def get_unit_words(unit_id: int, db: Session = Depends(get_db)):
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if unit is None:
        return {
            'success': False,
            'code': 403,
            'message': 'Bunday idli unit topilmadi',
            'data': None
        }

    words = db.query(Word).filter(unit.id == Word.unit_id).order_by(Word.unit_id, Word.id).all()

    custom_data = {
        'success': True,
        'code': 200,
        'message': 'Hammasi yaxshi',
        'data': [
            {
                'id': word.id,
                "word_en": word.word_en,
                'word_uz': word.word_uz,
                'comment': word.comment,
                'definition': word.definition,
                'phonetic': word.phonetic,
                'example': word.example,
                'word_classes': word.word_classes,
                'isFavorite': word.isFavorite,
                'unit_id': word.unit_id
            }
            for word in words
        ]
    }
    return jsonable_encoder(custom_data)


@word_router.put('/add-favorite/{id}', status_code=200)
async def add_favorite_words(id: int, db: Session = Depends(get_db)):
    word = db.query(Word).filter(Word.id == id).first()

    if word is None:
        return {
            'success': False,
            'code': 404,
            'message': 'Bunday idli so\'z topilmadi',
            'data': None
        }

    word.isFavorite = not word.isFavorite
    db.commit()

    custom_data = {
        'success': True,
        'code': 200,
        'message': 'Hammasi yaxshi',
        'data': "Word added to favorites list"
    }
    return jsonable_encoder(custom_data)


@word_router.put('/add-comment/{id}', status_code=200)
async def add_comment_words(id: int, comment: str, db: Session = Depends(get_db)):
    word = db.query(Word).filter(Word.id == id).first()

    if word is None:
        return {
            'success': False,
            'code': 404,
            'message': 'Bunday idli so\'z topilmadi',
            'data': None
        }

    word.comment = comment
    db.commit()

    custom_data = {
        'success': True,
        'code': 200,
        'message': 'Hammasi yaxshi',
        'data': "Comment is added successful"
    }
    return jsonable_encoder(custom_data)


@word_router.put('/edit-word/{id}', status_code=200)
async def edit_word(id: int, word: WordModel, db: Session = Depends(get_db)):
    word_old = db.query(Word).filter(Word.id == id).first()
    if word_old is None:
        return {
            'success': False,
            'code': 404,
            'message': 'Bunday idli so\'z topilmadi',
            'data': None
        }

    word_old.word_en = word.word_en
    word_old.word_uz = word.word_uz
    word_old.comment = word.comment
    word_old.definition = word.definition
    word_old.phonetic = word.phonetic
    word_old.example = word.example
    word_old.word_classes = word.word_classes
    word_old.isFavorite = word.isFavorite
    if word.unit_id is not None:
        word_old.unit_id = word.unit_id
    db.commit()

    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': 'So\'z muvaffaqiyatli tahrirlandi',
        'data': {
            'id': word_old.id,
            'word_en': word_old.word_en,
            'word_uz': word_old.word_uz,
            'comment': word_old.comment,
            'definition': word_old.definition,
            'phonetic': word_old.phonetic,
            'example': word_old.example,
            'word_classes': word_old.word_classes,
            'isFavorite': word_old.isFavorite,
            'unit_id': word_old.unit_id
        }
    })
