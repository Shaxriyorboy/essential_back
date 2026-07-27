"""Kunlik takrorlash (SRS) endpointlari — SRS_SPEC.md, 4-bo'lim.

Uchta endpoint:
    GET  /reviews/today   — bugungi navbat (kechikkanlar + yangi so'zlar)
    POST /reviews/submit  — sessiya natijalari (batch) + streak
    GET  /reviews/stats   — bosh ekran va profil uchun raqamlar

MUHIM (yo'l nomlari): `''` ishlatilgan, `'/'` emas. Aks holda FastAPI 307
redirect qiladi va `http` paketi redirect paytida `Authorization` header'ni
yo'qotadi -> 401. `progress_routes.py` dagi izohga qarang.
"""
import random

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

import srs
from auth import get_current_user
from database import get_db
from models import Book, Unit, User, UserWord, Word
from quiz_routes import pick_distractors
from schemes import ReviewSubmitModel
from streak import close_day

review_router = APIRouter(
    prefix='/reviews'
)

# --- Sozlanadigan parametrlar (SRS_SPEC.md, 12-bo'lim) ---------------------

DEFAULT_NEW_LIMIT = 8       # kuniga nechta YANGI so'z kiritiladi
DEFAULT_REVIEW_LIMIT = 25   # kuniga nechta takrorlash ko'rsatiladi
GOAL_MIN_ITEMS = 10         # kunni (streakni) yopish uchun minimal javob soni
EASY_START_COUNT = 3        # sessiya boshidagi "oson" (takrorlash) elementlar


def _ok(message: str, data):
    """Loyihadagi yagona javob formati."""
    return jsonable_encoder({
        "success": True,
        "code": 200,
        "message": message,
        "data": data,
    })


# --- Navbat tuzish ---------------------------------------------------------

def _build_item(stage: int, word: Word, pool: list) -> dict:
    """Bitta mashq elementini tuzadi.

    `word_en` HAR DOIM yuboriladi. Sabab: (1) javobdan keyin DARHOL feedback
    ko'rsatish uchun client to'g'ri javobni bilishi kerak — har savolda tarmoq
    so'rovi qilish mobil internetda qabul qilib bo'lmas sekinlik; (2) sessiya
    OFFLINE ham ishlashi kerak. Bu "aldash" xavfini tug'diradi, lekin reyting
    jadvali yo'q — foydalanuvchi faqat o'zini aldaydi. Baholash baribir
    serverda qayta bajariladi (`/reviews/submit`), ya'ni holat ishonchli.
    """
    exercise = srs.exercise_for_stage(stage)
    item = {
        "word_id": word.id,
        "stage": stage,
        "exercise": exercise,
        "word_en": word.word_en,
        "word_uz": word.word_uz,
        "definition": word.definition,
        "phonetic": word.phonetic,
        "word_classes": word.word_classes,
        "example": word.example,
    }
    if exercise == "mcq":
        options = pick_distractors(word, pool, 3) + [word.word_en]
        random.shuffle(options)
        item["options"] = options
    return item


def _interleave(due_items: list, new_items: list) -> list:
    """Takrorlash va yangi so'zlarni aralashtiradi.

    Sessiya boshida bir necha TAKRORLASH beriladi (oson start — foydalanuvchi
    darrov "men bilaman" hissini oladi), keyin yangi so'zlar aralashadi.
    Aralashtirish (interleaving) blok-blok berishdan yaxshiroq eslab qolinadi.
    """
    head = due_items[:EASY_START_COUNT]
    rest = due_items[EASY_START_COUNT:] + new_items
    random.shuffle(rest)
    return head + rest


@review_router.get('/today')
def get_today(
    local_date: str = Query(..., description="Client mahalliy sanasi YYYY-MM-DD"),
    new_limit: int = Query(DEFAULT_NEW_LIMIT, ge=0, le=50),
    review_limit: int = Query(DEFAULT_REVIEW_LIMIT, ge=0, le=100),
    book_id: int = Query(None, description="Ixtiyoriy: faqat shu kitobdan yangi so'z"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bugungi sessiya navbati.

    `review_limit` — kechikkan qarz to'planishining oldini oladi. 10 kun
    yo'qolgan foydalanuvchi 250 ta emas, 25 ta ko'radi. Bu SRS ning eng katta
    nuqsoni va uni shu yerda hal qilamiz.
    """
    # 1) Muddati kelgan takrorlashlar. `due_date` — ISO satr, shuning uchun
    #    satrli `<=` solishtirish sana bo'yicha to'g'ri ishlaydi.
    due_rows = (
        db.query(UserWord, Word)
        .join(Word, Word.id == UserWord.word_id)
        .filter(
            UserWord.user_id == user.id,
            UserWord.due_date.isnot(None),
            UserWord.due_date <= local_date,
        )
        .order_by(UserWord.due_date.asc(), UserWord.stage.asc())
        .limit(review_limit)
        .all()
    )

    # 2) Yangi so'zlar — hali ko'rilmaganlari, kitob/unit tartibida
    new_q = (
        db.query(Word)
        .join(Unit, Unit.id == Word.unit_id)
        .join(Book, Book.id == Unit.book_id)
        .outerjoin(
            UserWord,
            and_(UserWord.word_id == Word.id, UserWord.user_id == user.id),
        )
        .filter(UserWord.id.is_(None))
    )
    if book_id is not None:
        new_q = new_q.filter(Book.id == book_id)
    new_words = new_q.order_by(Book.id, Unit.id, Word.id).limit(new_limit).all()

    # 3) `mcq` uchun distraktor fondi — element so'zi bilan BIR XIL unitdan.
    #    Barcha kerakli unitlarni BITTA so'rovda olamiz (N+1 bo'lmasin).
    mcq_words = [w for uw, w in due_rows if uw.stage == 0] + list(new_words)
    unit_ids = {w.unit_id for w in mcq_words if w.unit_id is not None}
    pool_by_unit = {}
    if unit_ids:
        for w in db.query(Word).filter(Word.unit_id.in_(unit_ids)).all():
            pool_by_unit.setdefault(w.unit_id, []).append(w)

    due_items = [
        _build_item(uw.stage or 0, w, pool_by_unit.get(w.unit_id, []))
        for uw, w in due_rows
    ]
    new_items = [
        _build_item(0, w, pool_by_unit.get(w.unit_id, []))
        for w in new_words
    ]

    items = _interleave(due_items, new_items)

    return _ok("Bugungi navbat", {
        "goal": len(items),
        "due_count": len(due_items),
        "new_count": len(new_items),
        "items": items,
    })


# --- Natijalarni qabul qilish ---------------------------------------------

def _grade(answer, word: Word) -> bool:
    """Bitta javobni baholaydi.

    `recall_meaning` — o'zini baholash (bazadagi o'zbekcha tarjima ko'p variantli:
    "qo'rqqan, cho'chigan" — yozilganini avtomatik baholab bo'lmaydi).
    Qolganlari — `word_en` bilan solishtiriladi (imlo toleransi bilan).
    """
    if answer.exercise == "recall_meaning":
        return bool(answer.known)
    return srs.is_answer_correct(answer.answer, word.word_en)


@review_router.post('/submit')
def submit_reviews(
    body: ReviewSubmitModel,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Sessiya natijalarini qabul qiladi, SRS holatini yangilaydi va kunlik
    maqsad bajarilgan bo'lsa streakni yopadi.

    Baholash SERVERDA bajariladi — client'ga ishonmaymiz (quiz_routes.py bilan
    bir xil tamoyil).
    """
    answers = body.answers or []
    if not answers:
        return _ok("Javoblar bo'sh", {
            "correct": 0, "total": 0, "results": [], "stage_ups": [],
            "goal_met": False,
            "streak": {
                "current_streak": user.current_streak or 0,
                "longest_streak": user.longest_streak or 0,
                "last_active_date": user.last_active_date,
                "increased": False,
            },
        })

    word_ids = [a.word_id for a in answers]
    words = {w.id: w for w in db.query(Word).filter(Word.id.in_(word_ids)).all()}

    existing = {
        uw.word_id: uw
        for uw in db.query(UserWord).filter(
            UserWord.user_id == user.id,
            UserWord.word_id.in_(word_ids),
        ).all()
    }

    results = []
    stage_ups = []
    correct_count = 0

    for a in answers:
        word = words.get(a.word_id)
        if word is None:
            continue  # o'chirilgan so'z — jimgina o'tkazamiz

        uw = existing.get(a.word_id)
        if uw is None:
            # Birinchi marta ko'rilgan so'z — yozuv shu yerda tug'iladi
            init = srs.initial_state(body.local_date)
            uw = UserWord(user_id=user.id, word_id=a.word_id, **init)
            db.add(uw)
            existing[a.word_id] = uw

        before_stage = uw.stage or 0
        is_correct = _grade(a, word)
        if is_correct:
            correct_count += 1

        state = srs.next_state(
            {
                "stage": uw.stage, "stage_reps": uw.stage_reps, "step": uw.step,
                "ease": uw.ease, "reps": uw.reps, "lapses": uw.lapses,
            },
            is_correct,
            body.local_date,
        )
        for key, value in state.items():
            setattr(uw, key, value)
        uw.last_review_date = body.local_date

        if state["stage"] > before_stage:
            stage_ups.append(a.word_id)

        result = {
            "word_id": a.word_id,
            "correct": is_correct,
            "stage": state["stage"],
            "next_due": state["due_date"],
        }
        if not is_correct:
            # To'g'ri javobni qaytaramiz — foydalanuvchi o'rgansin
            result["expected"] = word.word_en
        results.append(result)

    total = len(results)
    score = round(correct_count / total * 100) if total else 0

    # Yangi `due_date` qiymatlari quyidagi so'rovga ko'rinishi uchun flush
    db.flush()

    # Kunlik maqsad ikki yo'l bilan bajariladi:
    #   1) kamida GOAL_MIN_ITEMS ta so'z takrorlandi, YOKI
    #   2) bugunga muddati kelgan so'z umuman qolmadi (ish tugadi).
    # Ikkinchi shart kam so'z qolgan foydalanuvchini jazolamaslik uchun: agar
    # navbatda bor-yo'g'i 4 ta so'z bo'lsa, 4 tasini bajarish ham kunni yopadi.
    remaining_due = (
        db.query(func.count(UserWord.id))
        .filter(UserWord.user_id == user.id,
                UserWord.due_date.isnot(None),
                UserWord.due_date <= body.local_date)
        .scalar()
    ) or 0
    goal_met = total > 0 and (total >= GOAL_MIN_ITEMS or remaining_due == 0)

    streak = {
        "current_streak": user.current_streak or 0,
        "longest_streak": user.longest_streak or 0,
        "last_active_date": user.last_active_date,
        "increased": False,
    }
    if goal_met:
        # `close_day` o'zi commit qiladi
        streak = close_day(db, user, body.local_date, "review", score)
    else:
        db.commit()

    return _ok("Qabul qilindi", {
        "correct": correct_count,
        "total": total,
        "results": results,
        "stage_ups": stage_ups,
        "goal_met": goal_met,
        "streak": streak,
    })


# --- Statistika ------------------------------------------------------------

@review_router.get('/stats')
def get_stats(
    local_date: str = Query(..., description="Client mahalliy sanasi YYYY-MM-DD"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bosh ekran ("Bugun") va profil uchun raqamlar."""
    today_done = (
        db.query(func.count(UserWord.id))
        .filter(UserWord.user_id == user.id,
                UserWord.last_review_date == local_date)
        .scalar()
    ) or 0

    due_today = (
        db.query(func.count(UserWord.id))
        .filter(UserWord.user_id == user.id,
                UserWord.due_date.isnot(None),
                UserWord.due_date <= local_date)
        .scalar()
    ) or 0

    due_tomorrow = (
        db.query(func.count(UserWord.id))
        .filter(UserWord.user_id == user.id,
                UserWord.due_date == srs.add_days(local_date, 1))
        .scalar()
    ) or 0

    by_stage = {str(i): 0 for i in range(5)}
    for stage, count in (
        db.query(UserWord.stage, func.count(UserWord.id))
        .filter(UserWord.user_id == user.id)
        .group_by(UserWord.stage)
        .all()
    ):
        by_stage[str(stage or 0)] = count

    # Faza 4 da to'ladi: so'z 3-darajadan yuqori VA suhbatda erkin ishlatilgan.
    # Hozir 0 qaytadi, lekin maydon hozirdan bo'lsin — client keyin o'zgarmaydi.
    active_words = (
        db.query(func.count(UserWord.id))
        .filter(UserWord.user_id == user.id,
                UserWord.stage >= 3,
                UserWord.active_uses >= 2)
        .scalar()
    ) or 0

    started = sum(by_stage.values())
    total_words = db.query(func.count(Word.id)).scalar() or 0

    return _ok("Statistika", {
        "today_done": today_done,
        "today_goal": min(due_today + DEFAULT_NEW_LIMIT,
                          DEFAULT_REVIEW_LIMIT + DEFAULT_NEW_LIMIT),
        "due_today": due_today,
        "due_tomorrow": due_tomorrow,
        "started_words": started,
        "total_words": total_words,
        "by_stage": by_stage,
        "active_words": active_words,
        "current_streak": user.current_streak or 0,
        "longest_streak": user.longest_streak or 0,
    })
