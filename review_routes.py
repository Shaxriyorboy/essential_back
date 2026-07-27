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
from sqlalchemy import and_, func, or_, tuple_
from sqlalchemy.orm import Session

import srs
from auth import get_current_user
from database import get_db
from models import Book, Unit, UnitCompletion, User, UserWord, Word
from gapfill import build_gap
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
    item = {
        "word_id": word.id,
        "stage": stage,
        "exercise": srs.exercise_for_stage(stage),
        "word_en": word.word_en,
        "word_uz": word.word_uz,
        "definition": word.definition,
        "phonetic": word.phonetic,
        "word_classes": word.word_classes,
        "example": word.example,
    }

    # MUHIM: bosqichga xos ma'lumot HAR DOIM yuboriladi, so'zning joriy
    # darajasidan qat'i nazar.
    #
    # Sabab: etaplarni CLIENT quradi. Sessiya boshlanganda so'z 0-darajada
    # bo'ladi, lekin o'sha sessiya ichida 3-darajagacha ko'tariladi — o'shanda
    # unga gap kerak bo'ladi. Agar faqat joriy darajaga mos ma'lumot
    # yuborsak, In context bosqichida ekran BO'SH chiqadi.
    options = pick_distractors(word, pool, 3) + [word.word_en]
    random.shuffle(options)
    item["options"] = options

    gap = build_gap(word.word_en, word.example)
    if gap is None:
        # ~1.5% so'zda misol gapda so'z topilmaydi (noto'g'ri fe'l yoki OCR
        # axlati). Client bunday so'zga In context o'rniga yozish mashqini
        # beradi — bosqich baribir o'tiladi, foydalanuvchi farqni sezmaydi.
        item["gap_sentence"] = None
        item["gap_answer"] = None
    else:
        item["gap_sentence"] = gap["sentence"]
        # Gapdan olib tashlangan AYNAN shakl (`hunted`). Client darhol
        # feedback ko'rsatishi uchun kerak — u `word_en` (`hunt`) bilan
        # solishtirsa, to'g'ri javobni xato deb ko'rsatib qo'yardi.
        item["gap_answer"] = gap["answer"]

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


def _unit_has_work_today(db: Session, user: User, unit_id: int,
                         local_date: str) -> bool:
    """Unitda bugun qilinadigan ish bormi.

    Mezon DARAJA emas, MUDDAT: so'z hali ko'rilmagan bo'lsa yoki muddati
    bugunga (yoki undan oldinga) kelgan bo'lsa — ish bor.
    """
    return db.query(Word.id).outerjoin(
        UserWord,
        and_(UserWord.word_id == Word.id, UserWord.user_id == user.id),
    ).filter(
        Word.unit_id == unit_id,
        or_(UserWord.id.is_(None), UserWord.due_date <= local_date),
    ).first() is not None


def _unit_touched_today(db: Session, user: User, unit_id: int,
                        local_date: str) -> bool:
    """Bu unit ustida BUGUN ishlanganmi."""
    return db.query(UserWord.id).join(
        Word, Word.id == UserWord.word_id
    ).filter(
        UserWord.user_id == user.id,
        Word.unit_id == unit_id,
        UserWord.last_review_date == local_date,
    ).first() is not None


def _unit_stage_progress(db: Session, user: User, unit_id, local_date: str):
    """Unitning nechta BOSQICHI tugatilgan: `(bajarilgan, jami)`.

    Jami bosqichlar = MAX_STAGE + 1 (Recognise, Recall, Produce).

    Bosqich `s` tugagan hisoblanadi:
      - s < MAX  -> unitning HAMMA so'zi `s` dan yuqori darajada
      - s == MAX -> hamma so'z MAX darajada VA muddati ertaga surilgan
                    (ya'ni yozish mashqi ham bajarilgan)

    Oxirgi shart muhim: so'z Recall etapi oxirida MAX darajaga "yetadi", lekin
    Produce mashqi hali bajarilmagan bo'ladi. Faqat `due_date` surilgani
    o'sha etap haqiqatan o'tganini bildiradi.
    """
    total = srs.MAX_STAGE_PHASE1 + 1
    if unit_id is None:
        return 0, total

    rows = (
        db.query(Word.id, UserWord.stage, UserWord.due_date)
        .outerjoin(
            UserWord,
            and_(UserWord.word_id == Word.id, UserWord.user_id == user.id),
        )
        .filter(Word.unit_id == unit_id)
        .all()
    )
    if not rows:
        return 0, total

    stages = [(r[1] or 0) for r in rows]
    dues = [r[2] for r in rows]

    done = 0
    for s in range(srs.MAX_STAGE_PHASE1):
        if all(st > s for st in stages):
            done += 1
    if (all(st >= srs.MAX_STAGE_PHASE1 for st in stages)
            and all(dd is not None and dd > local_date for dd in dues)):
        done += 1
    return done, total


def _session_unit(db: Session, user: User, local_date: str, book_id=None):
    """Sessiya uchun unitni tanlaydi. KUNIGA BITTA UNIT.

    Qoida (mahsulot qarori):
      - joriy unitda bugungi ish qolgan bo'lsa      -> o'sha unit
      - joriy unit BUGUN tugatilgan bo'lsa          -> yangi unit YO'Q (ertaga)
      - joriy unit oldinroq tugatilgan bo'lsa       -> keyingi unit ochiladi

    Nega kuniga bitta: cheksiz modelda foydalanuvchi bir kunda 15 ta unit
    qilib tashlashi mumkin edi (~300 so'z). Bir hafta o'tib ularning hammasi
    takrorlashga qaytadi va 300 ta kartani ko'rgan odam ilovani tashlab
    ketadi. Kunlik cheklov bu portlashning oldini oladi va tushunarli ritm
    beradi.

    `None` qaytsa — bugungi unit tugatilgan, yangisi ertaga ochiladi.
    """
    current = _current_unit_id(db, user)

    if current is not None:
        if _unit_has_work_today(db, user, current, local_date):
            return db.query(Unit).filter(Unit.id == current).first()
        # Ish qolmagan. Agar shu unit BUGUN tugatilgan bo'lsa — kunlik norma
        # bajarilgan, yangi unit ertaga.
        if _unit_touched_today(db, user, current, local_date):
            return None

    # Keyingi unit: birinchi ko'rilmagan so'zi bor unit
    nxt = _pick_new_words(db, user, 1, book_id)
    if nxt:
        return db.query(Unit).filter(Unit.id == nxt[0].unit_id).first()

    # Yangi so'z qolmagan — oxirgi unitda qolib ketamiz (faqat takrorlash bo'ladi)
    if current is not None:
        return db.query(Unit).filter(Unit.id == current).first()
    return db.query(Unit).join(Book, Book.id == Unit.book_id).order_by(Book.id, Unit.id).first()


@review_router.get('/session')
def get_session(
    local_date: str = Query(..., description="Client mahalliy sanasi YYYY-MM-DD"),
    review_limit: int = Query(DEFAULT_REVIEW_LIMIT, ge=0, le=100),
    book_id: int = Query(None, description="Ixtiyoriy: faqat shu kitobdan"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bir kunlik sessiya = BITTA UNIT, bosqichma-bosqich.

    Javob tuzilishi client'ga etaplarni qurish imkonini beradi:
      - `words`        — unitning BARCHA so'zlari + har birining joriy darajasi
      - `review_items` — oldingi unitlardan muddati kelgan so'zlar (alohida etap)

    Etaplarni client quradi: har daraja uchun o'sha darajadagi so'zlar QAYTA
    ARALASHTIRILIB beriladi. Aralashtirish har etapda takrorlanadi — aks holda
    foydalanuvchi so'zni emas, kartaning pozitsiyasini yodlab oladi.
    """
    unit = _session_unit(db, user, local_date, book_id)

    # `unit is None` — bugungi unit tugatilgan, yangisi ERTAGA ochiladi.
    # Bu holatda ham takrorlash bo'lishi mumkin, shuning uchun javobni to'liq
    # quramiz: faqat `words` bo'sh va `unit_done_today` bayrog'i qo'yiladi.
    unit_done_today = unit is None

    unit_words = (
        db.query(Word).filter(Word.unit_id == unit.id).order_by(Word.id).all()
        if unit is not None else []
    )
    pool = list(unit_words)

    stage_by_word = {
        uw.word_id: (uw.stage or 0)
        for uw in db.query(UserWord)
        .filter(UserWord.user_id == user.id,
                UserWord.word_id.in_([w.id for w in unit_words]))
        .all()
    } if unit_words else {}

    words = [
        _build_item(stage_by_word.get(w.id, 0), w, pool)
        for w in unit_words
    ]

    # Oldingi unitlardan muddati kelganlar — alohida "Takrorlash" etapi
    unit_word_ids = {w.id for w in unit_words}
    due_rows = (
        db.query(UserWord, Word)
        .join(Word, Word.id == UserWord.word_id)
        .filter(
            UserWord.user_id == user.id,
            UserWord.due_date.isnot(None),
            UserWord.due_date <= local_date,
            ~Word.id.in_(unit_word_ids) if unit_word_ids else True,
        )
        .order_by(UserWord.due_date.asc(), UserWord.stage.asc())
        .limit(review_limit)
        .all()
    )
    due_unit_ids = {w.unit_id for uw, w in due_rows if w.unit_id is not None}
    due_pool = {}
    if due_unit_ids:
        for w in db.query(Word).filter(Word.unit_id.in_(due_unit_ids)).all():
            due_pool.setdefault(w.unit_id, []).append(w)
    review_items = [
        _build_item(uw.stage or 0, w, due_pool.get(w.unit_id, []))
        for uw, w in due_rows
    ]

    book = (
        db.query(Book).filter(Book.id == unit.book_id).first()
        if unit is not None else None
    )

    return _ok("Sessiya", {
        "unit": None if unit is None else {
            "id": unit.id,
            "name": unit.name,
            "book_id": unit.book_id,
            "book_name": book.name if book else None,
        },
        "words": words,
        "review_items": review_items,
        # True — bugungi unit tugatilgan, yangisi ertaga ochiladi
        "unit_done_today": unit_done_today,
        "max_stage": srs.MAX_STAGE_PHASE1,
    })


# --- Natijalarni qabul qilish ---------------------------------------------

def _grade(answer, word: Word) -> bool:
    """Bitta javobni baholaydi.

    Hamma mashq turi `word_en` bilan solishtiriladi (imlo toleransi bilan).

    `recall_meaning` — ESKI tur (o'zini baholash). Endi ishlatilmaydi, lekin
    offline navbatda qolgan javoblar uchun qo'llab-quvvatlanadi.
    """
    if answer.exercise == srs.LEGACY_SELF_RATED:
        return bool(answer.known)

    if answer.exercise == "gap_fill":
        # Gapdagi shakl ham (`hunted`), asosiy shakl ham (`hunt`) qabul
        # qilinadi — grammatikani bilmagani uchun jazolamaymiz.
        gap = build_gap(word.word_en, word.example)
        if gap is not None and srs.is_answer_correct(answer.answer, gap["answer"]):
            return True

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
        streak = close_day(db, user, body.local_date, "review", score)

    # MUHIM: commit HAR DOIM shu yerda bajariladi.
    #
    # Avval commit `close_day` ga tashlab qo'yilgan edi, u esa kun ALLAQACHON
    # yopilgan bo'lsa commit qilmaydi (StreakDay yozuvi bor -> darrov qaytadi).
    # Natijada kun ichidagi IKKINCHI va undan keyingi sessiyalarda SRS holati
    # jimgina yo'qolardi: javob "to'g'ri, stage 2" deb qaytardi, lekin bazaga
    # yozilmasdi. Etap modelida (kuniga 3 ta sessiya) bu har kuni sodir bo'lardi.
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

    # ILOVANING BOSH METRIKASI: so'z 4-darajada — ya'ni barcha yozma
    # bosqichlardan o'tgan VA suhbatda erkin ishlatilgan.
    # Ko'tarilish `speaking_routes._record_active_uses()` da bo'ladi.
    active_words = (
        db.query(func.count(UserWord.id))
        .filter(UserWord.user_id == user.id, UserWord.stage >= 4)
        .scalar()
    ) or 0

    started = sum(by_stage.values())
    total_words = db.query(func.count(Word.id)).scalar() or 0

    # Kunlik maqsad = joriy UNIT so'zlari + muddati kelgan takrorlashlar.
    # Sessiya endi unit asosida quriladi, shuning uchun maqsad ham shunga
    # bog'lanadi (avval qat'iy DEFAULT_NEW_LIMIT edi).
    unit = _session_unit(db, user, local_date)
    unit_done_today = unit is None
    unit_size = (
        db.query(func.count(Word.id)).filter(Word.unit_id == unit.id).scalar() or 0
    ) if unit is not None else 0
    unit_word_ids = (
        [w.id for w in db.query(Word.id).filter(Word.unit_id == unit.id).all()]
        if unit is not None else []
    )
    due_outside_unit = (
        db.query(func.count(UserWord.id))
        .filter(UserWord.user_id == user.id,
                UserWord.due_date.isnot(None),
                UserWord.due_date <= local_date,
                ~UserWord.word_id.in_(unit_word_ids) if unit_word_ids else True)
        .scalar()
    ) or 0

    stages_done, stages_total = _unit_stage_progress(
        db, user, unit.id if unit is not None else None, local_date)
    if unit_done_today:
        stages_done = stages_total

    return _ok("Statistika", {
        # Kunlik maqsad endi BOSQICH bilan o'lchanadi, so'z soni bilan emas.
        # Sabab: `today_done` turli so'zlarni sanaydi, unit esa 3 ta bosqichdan
        # iborat. Birinchi etapdan keyin 20 ta so'z "ishlangan" bo'lardi va
        # halqa to'lib "maqsad bajarildi" deb turardi — holbuki oldinda yana
        # ikkita etap bor edi.
        "today_done": stages_done,
        "today_goal": stages_total,
        "words_done_today": today_done,
        "unit_name": unit.name if unit is not None else None,
        "unit_done_today": unit_done_today,
        "unit_size": unit_size,
        "due_today": due_today,
        "due_tomorrow": due_tomorrow,
        "started_words": started,
        "total_words": total_words,
        "by_stage": by_stage,
        "active_words": active_words,
        "current_streak": user.current_streak or 0,
        "longest_streak": user.longest_streak or 0,
    })
