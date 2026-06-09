from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session
from schemes import WordModel
from models import Word, Unit, UserFavorite, WordComment, User
from database import get_db
from auth import get_current_user, get_current_user_optional

word_router = APIRouter(
    prefix='/word'
)


def _user_annotations(db: Session, user, word_ids):
    """Berilgan so'zlar uchun foydalanuvchining favorite id'lari (set) va
    izohlari (word_id -> text) ni qaytaradi. Login bo'lmasa bo'sh."""
    if user is None or not word_ids:
        return set(), {}
    favs = db.query(UserFavorite.word_id).filter(
        UserFavorite.user_id == user.id,
        UserFavorite.word_id.in_(word_ids),
    ).all()
    fav_ids = {f[0] for f in favs}
    comments = db.query(WordComment.word_id, WordComment.text).filter(
        WordComment.user_id == user.id,
        WordComment.word_id.in_(word_ids),
    ).all()
    comment_map = {c[0]: (c[1] or '') for c in comments}
    return fav_ids, comment_map


def _word_dict(word, fav_ids, comment_map):
    """So'zni JSON'ga aylantiradi — isFavorite/comment PER-USER."""
    return {
        'id': word.id,
        'word_en': word.word_en,
        'word_uz': word.word_uz,
        'comment': comment_map.get(word.id, ''),
        'definition': word.definition,
        'phonetic': word.phonetic,
        'example': word.example,
        'word_classes': word.word_classes,
        'isFavorite': word.id in fav_ids,
        'unit_id': word.unit_id,
    }


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
async def get_favorite_words(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_optional),
):
    """Joriy foydalanuvchining saralangan so'zlari (per-user)."""
    if user is None:
        return jsonable_encoder(
            {'success': True, 'code': 200, 'message': 'Hammasi yaxshi', 'data': []})

    fav_word_ids = [
        f[0] for f in db.query(UserFavorite.word_id)
        .filter(UserFavorite.user_id == user.id).all()
    ]
    if not fav_word_ids:
        return jsonable_encoder(
            {'success': True, 'code': 200, 'message': 'Hammasi yaxshi', 'data': []})

    words = db.query(Word).filter(Word.id.in_(fav_word_ids)).order_by(Word.id).all()
    fav_ids = set(fav_word_ids)
    _, comment_map = _user_annotations(db, user, fav_word_ids)

    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': 'Hammasi yaxshi',
        'data': [_word_dict(w, fav_ids, comment_map) for w in words],
    })


@word_router.get('/{unit_id}', status_code=200)
async def get_unit_words(
    unit_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_optional),
):
    """Unit so'zlari. isFavorite/comment — PER-USER (login bo'lsa). Login
    bo'lmasa so'zlar baribir ko'rinadi (isFavorite=false, comment='')."""
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if unit is None:
        return {
            'success': False,
            'code': 403,
            'message': 'Bunday idli unit topilmadi',
            'data': None
        }

    words = db.query(Word).filter(Word.unit_id == unit_id).order_by(
        Word.unit_id, Word.id).all()
    fav_ids, comment_map = _user_annotations(db, user, [w.id for w in words])

    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': 'Hammasi yaxshi',
        'data': [_word_dict(w, fav_ids, comment_map) for w in words],
    })


@word_router.put('/add-favorite/{id}', status_code=200)
async def add_favorite_words(
    id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Joriy foydalanuvchi uchun saralashni almashtiradi (toggle, per-user)."""
    word = db.query(Word).filter(Word.id == id).first()
    if word is None:
        raise HTTPException(status_code=404, detail="Bunday idli so'z topilmadi")

    existing = db.query(UserFavorite).filter(
        UserFavorite.user_id == user.id,
        UserFavorite.word_id == id,
    ).first()

    if existing:
        db.delete(existing)
        message = "Saralangandan olib tashlandi"
    else:
        db.add(UserFavorite(user_id=user.id, word_id=id))
        message = "Saralanganlarga qo'shildi"
    db.commit()

    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': message,
        'data': None,
    })


@word_router.put('/add-comment/{id}', status_code=200)
async def add_comment_words(
    id: int,
    comment: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Joriy foydalanuvchining shaxsiy izohini saqlaydi/yangilaydi (per-user)."""
    word = db.query(Word).filter(Word.id == id).first()
    if word is None:
        raise HTTPException(status_code=404, detail="Bunday idli so'z topilmadi")

    row = db.query(WordComment).filter(
        WordComment.user_id == user.id,
        WordComment.word_id == id,
    ).first()
    if row:
        row.text = comment
    else:
        db.add(WordComment(user_id=user.id, word_id=id, text=comment))
    db.commit()

    return jsonable_encoder({
        'success': True,
        'code': 200,
        'message': 'Izoh saqlandi',
        'data': None,
    })


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
