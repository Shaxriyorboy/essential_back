import random
from fastapi import FastAPI, Depends, HTTPException, APIRouter
from fastapi.encoders import jsonable_encoder
from schemes import BaseModel,UnitModel
from models import Book,Unit,Word
from database import engine,session

quiz_router = APIRouter(
    prefix='/quiz'
)

session = session(bind=engine)

@quiz_router.get('/')
async def get_quiz():
    return {"message": "Bu sahifa savollar uchun"}  

def build_question(word: Word, all_words: list, options_count: int = 4):
    """
    Bitta so'z uchun savol va variantlar tuzadi
    """
    # To‘g‘ri javob
    correct_answer = word.word_en  # <-- sizda to‘g‘ri javob ustuni qaysi bo‘lsa (masalan: translation)
    
    # Boshqa so‘zlardan noto‘g‘ri javoblarni tanlaymiz
    other_words = [w.word_en for w in all_words if w.id != word.id]
    wrong_answers = random.sample(other_words, min(options_count - 1, len(other_words)))
    
    # Variantlarni aralashtiramiz
    options = wrong_answers + [correct_answer]
    random.shuffle(options)
    
    return {
        "id": word.id,
        "question": word.word_uz,   # savol (masalan inglizcha so‘z)
        "options": options,      # variantlar
        "correct": correct_answer  # frontendga jo‘natmaslik ham mumkin (lekin test uchun qo‘yib qo‘ydim)
    }


@quiz_router.get("/book/{book_id}")
def get_book_quiz(book_id: int, count: int = 10):
    # Shu book'ga tegishli unitlarni topamiz
    units = session.query(Unit).filter(Unit.book_id == book_id).all()
    if not units:
        raise HTTPException(status_code=404, detail="Kitob bo‘yicha unitlar topilmadi")

    # Shu unitlardan wordlarni yig‘amiz
    words = session.query(Word).filter(Word.unit_id.in_([u.id for u in units])).all()
    if not words:
        raise HTTPException(status_code=404, detail="Kitob bo‘yicha so‘zlar topilmadi")

    # Random test tuzish
    selected = random.sample(words, min(count, len(words)))
    return jsonable_encoder({
        "success": True,
        "status_code": 200,
        "data": [build_question(w, words) for w in selected]
    })


@quiz_router.get("/unit/{unit_id}")
def get_unit_quiz(unit_id: int, count: int = 10):
    words = session.query(Word).filter(Word.unit_id == unit_id).all()
    if not words:
        raise HTTPException(status_code=404, detail="Unit bo‘yicha so‘zlar topilmadi")

    selected = random.sample(words, min(count, len(words)))
    return jsonable_encoder({
        "success": True,
        "status_code": 200,
        "data": [build_question(w, words) for w in selected]
    })