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
from sqlalchemy import and_, func, tuple_
from sqlalchemy.orm import Session

import srs
from auth import get_current_user
from database import get_db
from models import Book, Unit, UnitCompletion, User, UserWord, Word
from quiz_routes import pick_distractors
from schemes import ReviewSubmitModel
from streak import close_day

review_router = APIRouter(
    prefix='/reviews'
)

# --- Sozlanadigan parametrlar (SRS_SPEC.md, 12-bo'lim) ---------------------

DEFAULT_NEW_LIMIT = 8       # kuniga nechta YANGI so'z kiritiladi
DEFAULT_REVIEW_LIMIT = 25   # kuniga nechta takrorlash ko'rsatiladi
# Kunni (streakni) yopish uchun bugun kamida shuncha TURLI so'z ishlangan
# bo'lishi kerak. DEFAULT_NEW_LIMIT bilan tenglashtirilgan: standart sessiyani
# oxirigacha bajargan foydalanuvchi streakini oladi.
GOAL_MIN_ITEMS = 8
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


def _as_naive(dt):
    """tz-aware va naive datetime'larni solishtirish uchun bir ko'rinishga keltiradi.
    (SQLite naive, Postgres aware qaytarishi mumkin — to'g'ridan-to'g'ri
    solishtirish TypeError beradi.)"""
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _current_unit_id(db: Session, user: User):
    """Foydalanuvchi OXIRGI ishlagan unit.

    Ikkita manba solishtiriladi va kechrog'i olinadi:
      - SRS'ga oxirgi kirgan so'zning uniti (`UserWord.first_seen_at`)
      - Kitoblar tabida oxirgi tugatilgan unit (`UnitCompletion.completed_at`)

    Ikkinchisi muhim: foydalanuvchi Kitoblar tabida 12-unitni ishlagan bo'lsa,
    "Bugun" sessiyasi ham o'sha yerdan davom etishi kerak — avval sessiya bu
    tanlovni umuman bilmasdi va har doim 1-kitobdan berardi.

    Hech qanday faoliyat bo'lmasa `None` (eng boshidan boshlanadi).
    """
    candidates = []

    row = (
        db.query(Word.unit_id, UserWord.first_seen_at)
        .join(UserWord, UserWord.word_id == Word.id)
        .filter(UserWord.user_id == user.id)
        .order_by(UserWord.first_seen_at.desc())
        .first()
    )
    if row and row[0] is not None and row[1] is not None:
        candidates.append((_as_naive(row[1]), row[0]))

    row = (
        db.query(UnitCompletion.unit_id, UnitCompletion.completed_at)
        .filter(UnitCompletion.user_id == user.id)
        .order_by(UnitCompletion.completed_at.desc())
        .first()
    )
    if row and row[0] is not None and row[1] is not None:
        candidates.append((_as_naive(row[1]), row[0]))

    if not candidates:
        return None
    return max(candidates)[0 + 1]


def _pick_new_words(db: Session, user: User, limit: int, book_id=None) -> list:
    """Yangi (hali ko'rilmagan) so'zlarni tanlaydi.

    Qoida:
      1. Oxirgi ishlagan unitdan DAVOM etadi
      2. U unit tugagan bo'lsa — keyingi unitlarga o'tadi
      3. Umuman faoliyat bo'lmasa — eng boshidan (1-kitob, 1-unit)
      4. Oxiriga yetgan bo'lsa — qolgan o'tkazib yuborilganlarini oladi
    """
    if limit <= 0:
        return []

    def unseen_query():
        q = (
            db.query(Word)
            .join(Unit, Unit.id == Word.unit_id)
            .join(Book, Book.id == Unit.book_id)
            .outerjoin(
                UserWord,
                and_(UserWord.word_id == Word.id, UserWord.user_id == user.id),
            )
            .filter(UserWord.id.is_(None))
        )
        return q.filter(Book.id == book_id) if book_id is not None else q

    picked = []
    current_unit = _current_unit_id(db, user)

    if current_unit is not None:
        # 1) Joriy unitning qolgan so'zlari
        picked = (
            unseen_query()
            .filter(Word.unit_id == current_unit)
            .order_by(Word.id)
            .limit(limit)
            .all()
        )
        if len(picked) < limit:
            # 2) Joriy unitdan KEYINGI unitlar
            pos = (
                db.query(Book.id, Unit.id)
                .join(Unit, Unit.book_id == Book.id)
                .filter(Unit.id == current_unit)
                .first()
            )
            if pos is not None:
                after = unseen_query().filter(
                    tuple_(Book.id, Unit.id) > tuple_(pos[0], pos[1])
                )
                picked += (
                    after.order_by(Book.id, Unit.id, Word.id)
                    .limit(limit - len(picked))
                    .all()
                )

    if len(picked) < limit:
        # 3/4) Boshidan (yangi foydalanuvchi) yoki o'tkazib yuborilganlar
        got = {w.id for w in picked}
        rest = unseen_query().order_by(Book.id, Unit.id, Word.id).limit(limit * 3).all()
        for w in rest:
            if w.id not in got:
                picked.append(w)
                if len(picked) >= limit:
                    break

    return picked[:limit]


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

    # 2) Yangi so'zlar — oxirgi ishlagan unitdan davom etadi
    new_words = _pick_new_words(db, user, new_limit, book_id)

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

    # Kunlik maqsad: BUGUN kamida GOAL_MIN_ITEMS ta TURLI so'z ishlangan bo'lsa.
    #
    # Hisob kumulyativ — kun davomida bir necha sessiya qilgan foydalanuvchining
    # mehnati qo'shiladi (5 ta + 5 ta = 10).
    #
    # MUHIM: bu yerda avval "muddati kelgan so'z qolmadimi" deb tekshirilardi.
    # Same-day takrorlash yoqilgach o'sha shart buzildi — so'zlar o'sha kuniyoq
    # qayta navbatga tushgani uchun "qolmadi" holati deyarli yuzaga kelmaydi va
    # streak umuman yopilmay qoldi. Endi mezon sof mehnat hajmi.
    answered_today = (
        db.query(func.count(UserWord.id))
        .filter(UserWord.user_id == user.id,
                UserWord.last_review_date == body.local_date)
        .scalar()
    ) or 0

    # Zaxira: butun korpus tugagan bo'lsa (yangi so'z ham, muddati kelgani ham
    # yo'q) kam ish bilan ham kun yopiladi — foydalanuvchi aybdor emas.
    unseen_left = (
        db.query(func.count(Word.id))
        .outerjoin(
            UserWord,
            and_(UserWord.word_id == Word.id, UserWord.user_id == user.id),
        )
        .filter(UserWord.id.is_(None))
        .scalar()
    ) or 0

    goal_met = total > 0 and (
        answered_today >= GOAL_MIN_ITEMS or unseen_left == 0
    )

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
