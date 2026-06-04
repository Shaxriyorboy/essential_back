import random
from fastapi import Depends, HTTPException, APIRouter
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session
from models import Unit, Word, User
from database import get_db
from auth import get_current_user
from schemes import QuizSubmitModel
from streak import close_day, QUIZ_PASS_PERCENT

quiz_router = APIRouter(
    prefix='/quiz'
)


@quiz_router.get('/')
async def get_quiz():
    return {"message": "Bu sahifa savollar uchun"}


def build_question(word: Word, all_words: list, options_count: int = 4):
    """Bitta so'z uchun savol va variantlar tuzadi"""
    correct_answer = word.word_en

    # Boshqa so'zlardan noto'g'ri javoblarni tanlaymiz
    other_words = [w.word_en for w in all_words if w.id != word.id]
    wrong_answers = random.sample(other_words, min(options_count - 1, len(other_words)))

    options = wrong_answers + [correct_answer]
    random.shuffle(options)

    return {
        "id": word.id,
        "question": word.word_uz,
        "options": options,
        "correct": correct_answer
    }


@quiz_router.get("/book/{book_id}")
def get_book_quiz(book_id: int, count: int = 10, db: Session = Depends(get_db)):
    # Shu book'ga tegishli unitlarni topamiz
    units = db.query(Unit).filter(Unit.book_id == book_id).all()
    if not units:
        raise HTTPException(status_code=404, detail="Kitob bo‘yicha unitlar topilmadi")

    # Shu unitlardan wordlarni yig'amiz
    words = db.query(Word).filter(Word.unit_id.in_([u.id for u in units])).all()
    if not words:
        raise HTTPException(status_code=404, detail="Kitob bo‘yicha so‘zlar topilmadi")

    selected = random.sample(words, min(count, len(words)))
    return jsonable_encoder({
        "success": True,
        "status_code": 200,
        "data": [build_question(w, words) for w in selected]
    })


@quiz_router.get("/unit/{unit_id}")
def get_unit_quiz(unit_id: int, count: int = 10, db: Session = Depends(get_db)):
    words = db.query(Word).filter(Word.unit_id == unit_id).all()
    if not words:
        raise HTTPException(status_code=404, detail="Unit bo‘yicha so‘zlar topilmadi")

    selected = random.sample(words, min(count, len(words)))
    return jsonable_encoder({
        "success": True,
        "status_code": 200,
        "data": [build_question(w, words) for w in selected]
    })


@quiz_router.post("/submit")
def submit_quiz(
    body: QuizSubmitModel,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Quiz javoblarini SERVER baholaydi (client'ga ishonmaymiz) va natija
    >= 80% bo'lsa foydalanuvchining bugungi streakini yopadi.

    Kun client'ning mahalliy sanasi (`local_date`) bo'yicha hisoblanadi."""
    answers = body.answers
    total = len(answers)
    if total == 0:
        raise HTTPException(status_code=400, detail="Javoblar bo'sh")

    # So'zlarni bitta so'rovda olib, id -> to'g'ri javob (word_en) xaritasini tuzamiz
    word_ids = [a.word_id for a in answers]
    words = db.query(Word).filter(Word.id.in_(word_ids)).all()
    correct_by_id = {w.id: (w.word_en or "").strip().lower() for w in words}

    correct = 0
    for a in answers:
        right = correct_by_id.get(a.word_id)
        if right is not None and (a.answer or "").strip().lower() == right:
            correct += 1

    score = round(correct / total * 100)
    passed = score >= QUIZ_PASS_PERCENT

    streak = {
        "current_streak": user.current_streak or 0,
        "longest_streak": user.longest_streak or 0,
        "last_active_date": user.last_active_date,
        "increased": False,
    }
    if passed:
        streak = close_day(db, user, body.local_date, "quiz", score)

    return jsonable_encoder({
        "success": True,
        "code": 200,
        "message": "Natija qabul qilindi",
        "data": {
            "score": score,
            "correct": correct,
            "total": total,
            "passed": passed,
            "pass_percent": QUIZ_PASS_PERCENT,
            "streak": streak,
        },
    })
