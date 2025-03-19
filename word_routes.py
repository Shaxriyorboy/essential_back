from fastapi import APIRouter
from models import Word,Unit
from fastapi.encoders import jsonable_encoder
from schemes import BaseModel, WordModel
from database import session,engine

word_router = APIRouter(
    prefix='/word'
)

session = session(bind=engine)

@word_router.post('/add-word')
async def add_new_word(word: WordModel):

    unit = session.query(Unit).filter(Unit.id==word.unit_id).first()
    if unit is None:
        return {
            'success':False,
            'code': 403,
            'message': 'Bunday idli kitob topilmadi',
            'data': None
        }

    new_word = Word(
        word_en = word.word_en,
        word_uz = word.word_uz,
        comment = word.comment,
        definition = word.definition,
        phonetic = word.phonetic,
        example = word.example,
        word_classes = word.word_classes,
        isFavorite = word.isFavorite,
        unit_id = word.unit_id
    )

    session.add(new_word)
    session.commit()

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

@word_router.get('/{unit_id}',status_code=200)
async def get_unit_words(unit_id:int):
    unit = session.query(Unit).filter(Unit.id == unit_id).first()
    if unit is None:
        return {
            'success':False,
            'code': 403,
            'message': 'Bunday idli unit topilmadi',
            'data': None
        }
    
    words = session.query(Word).filter(Word.unit_id==unit_id).all()

    custom_data = {
        'success':True,
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