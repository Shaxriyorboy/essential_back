"""AI Speaking Partner — `POST /speaking/chat`.

Dizayn hujjati: essential ilovasi repo'sidagi SPEAKING_PARTNER_SPEC.md.

Context (system prompt + USER + TARGET WORDS) SHU YERDA quriladi (app emas) —
shunda promptni app yangilamasdan, faqat backend deploy qilib o'zgartirsa bo'ladi.
"""
import json
import os
import re
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from datetime import timedelta

from fastapi import Header

from auth import get_current_user
from database import get_db
from gemini import GeminiError, generate_chat
from models import AiUsage, Book, SpeakingHistory, Unit, User, UserFavorite, Word
from schemes import SpeakingChatModel, SpeakingConsumeModel
from tiers import daily_limit_seconds, effective_tier, model_for, TIER_DAILY_SECONDS

speaking_router = APIRouter(prefix='/speaking')

# Bitta turn'da qo'shilishi mumkin bo'lgan eng ko'p vaqt (aldashni cheklash).
MAX_TURN_SECONDS = 180

# Gemini kontekstiga (va qaytariladigan tarixga) qo'shiladigan eng ko'p xabar —
# promptni cheklaydi. Har (user, suhbat) uchun DB'da shu miqdorda qator saqlanadi.
MAX_HISTORY_MESSAGES = 20

# Admin panel (essential_admin) uchun maxfiy kalit. Railway'da ADMIN_SECRET
# bilan o'rnatiladi; admin panel uni X-Admin-Secret header'da yuboradi.
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")


def require_admin_secret(x_admin_secret: str = Header(default="")):
    """Admin panel endpoint'lari uchun — X-Admin-Secret headerni tekshiradi.

    (Admin panel frontend-only, JWT yo'q — shuning uchun maxfiy kalit ishlatamiz.)"""
    if not ADMIN_SECRET or x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Admin huquqi kerak")
    return True

# Promptni juda kattalashtirib yubormaslik uchun target so'zlar soni cheklanadi.
MAX_TARGET_WORDS = 40

_CEFR = {1: "A1", 2: "A2", 3: "B1", 4: "B2", 5: "C1", 6: "C2"}
_LOCALE_LANG = {"uz": "Uzbek", "ru": "Russian", "en": "English"}

# Sessiya yangi ochilganda (foydalanuvchi hali gapirmagan) AI o'zi boshlashi uchun.
_GREETING_KICK = (
    "(The user just opened the session and hasn't spoken yet. Greet them warmly "
    "by name in English; if their streak is above zero, briefly acknowledge it to "
    "encourage them. Then start the conversation with ONE easy, concrete question, "
    "naturally using one target word.)"
)

_SYSTEM_PROMPT = (
    "You are \"Essi\", a warm, patient, encouraging English speaking partner inside "
    "a vocabulary-learning app. You are talking with {name}, a {native}-speaking "
    "English learner at CEFR level {level} (current streak: {streak} days). Your goal "
    "is a natural spoken conversation that helps them PRACTICE speaking — above all "
    "using the TARGET WORDS listed below.\n\n"
    "Calibrate your vocabulary and grammar to {level}:\n"
    "- A1/A2: very simple, common words; short present-tense sentences; one idea at a time.\n"
    "- B1/B2: everyday fluent language; introduce a few natural idioms.\n"
    "- C1/C2: rich, native-like speech.\n"
    "If the user is clearly stronger or weaker than {level}, adapt to them.\n\n"
    "LENGTH — THIS IS YOUR MOST IMPORTANT RULE. Keep replies short and match the moment:\n"
    "- Default to BRIEF: usually ONE short sentence, sometimes two. Your reply is read "
    "aloud by text-to-speech and the user has a limited daily time budget — a long reply "
    "bores them and wastes their time.\n"
    "- Hard limits by level, NEVER exceed: A1/A2 -> 1-2 short sentences; B1/B2 -> up to 2; "
    "C1/C2 -> up to 3. Most turns should use FEWER than the limit.\n"
    "- MIRROR the user's energy: a short or one-word answer gets a short reply; a quick "
    "question gets a quick answer. Only when the user shares something substantial, tells "
    "a story, or explicitly asks you to explain may you use your upper limit — and even "
    "then stay tight and make ONE point, not several.\n"
    "- NEVER monologue, lecture, give lists, stack multiple explanations, or ask more than "
    "one question. One thought, then ONE short follow-up question. When in doubt, say less.\n"
    "\n"
    "Conversation style:\n"
    "- React to what the user actually said (refer back to their words) before moving on; "
    "stay on topic and build on earlier turns.\n"
    "- End with ONE simple, specific follow-up question to keep them talking. Vary your "
    "questions and openers — never repeat the same one twice.\n"
    "- Naturally weave in 1-2 TARGET WORDS per reply and gently steer topics so the user "
    "gets chances to use them. Never force more than two, and don't reuse the same target "
    "word every turn.\n"
    "- If the user gives a one-word or low-effort answer, draw them out with an easy, "
    "concrete question.\n"
    "- If the user writes in {native} or goes off-topic, answer briefly and warmly, then "
    "guide them back to practicing in English.\n"
    "- Use the user's name occasionally to encourage them, but don't over-praise.\n\n"
    "Because your reply is READ ALOUD by text-to-speech:\n"
    "- Write numbers and symbols as words (\"twenty twenty-five\", not \"2025\"; \"percent\", "
    "not \"%\").\n"
    "- \"reply\" must be clean, natural spoken sentences only — no lists, markdown, emoji, "
    "or abbreviations.\n\n"
    "Corrections (do this WITHOUT breaking the conversation flow):\n"
    "- Put grammar/word-choice fixes in the \"corrections\" field, NEVER inside \"reply\".\n"
    "- Correct only MEANINGFUL mistakes — at most 1-2 per turn. For A1/A2, ignore tiny slips "
    "(articles, minor typos) and fix only what blocks understanding.\n"
    "- Each correction's \"note\" is a short, kind explanation written in {native}.\n"
    "- If the user is stuck on a word, briefly explain it in {native} inside \"reply\", then "
    "continue in English.\n\n"
    "Output fields:\n"
    "- \"reply\": your spoken response only — short, obeying the LENGTH rule above.\n"
    "- \"corrections\": meaningful fixes as described (empty list if nothing is worth correcting).\n"
    "- \"target_words_used_by_user\": the TARGET WORDS (base form, exactly as listed) that the "
    "USER actually used in THEIR latest message; empty list if none.\n"
    "- \"target_words_introduced\": the TARGET WORDS that YOU used in your \"reply\" this turn."
)


def _book_number(name: str):
    """ \"Essential 3\" -> 3. Raqam topilmasa None."""
    if not name:
        return None
    m = re.search(r"\d+", name)
    return int(m.group()) if m else None


def _cefr_for_number(n) -> str:
    if not n or n <= 1:
        return "A1"
    if n >= 6:
        return "C2"
    return _CEFR[n]


def _words_and_level(db: Session, user: User, payload: SpeakingChatModel):
    """source bo'yicha (words, level, label) qaytaradi.

    - unit:      o'sha unit so'zlari + unit kitobining CEFR'i + unit nomi
    - favorites: foydalanuvchi sevimlilari + ENG YUQORI kitob CEFR'i + "Favorites"
    """
    if payload.source == "favorites":
        fav_ids = [
            f[0] for f in db.query(UserFavorite.word_id)
            .filter(UserFavorite.user_id == user.id).all()
        ]
        words = (
            db.query(Word).filter(Word.id.in_(fav_ids)).order_by(Word.id).all()
            if fav_ids else []
        )
        level = "A1"
        if words:
            unit_ids = list({w.unit_id for w in words})
            units = db.query(Unit).filter(Unit.id.in_(unit_ids)).all()
            book_ids = list({u.book_id for u in units})
            books = db.query(Book).filter(Book.id.in_(book_ids)).all()
            nums = [n for n in (_book_number(b.name) for b in books) if n]
            if nums:
                level = _cefr_for_number(max(nums))
        return words, level, "Favorites"

    # source == "unit"
    if payload.unit_id is None:
        raise HTTPException(status_code=400, detail="source=unit uchun unit_id kerak")
    unit = db.query(Unit).filter(Unit.id == payload.unit_id).first()
    if unit is None:
        raise HTTPException(status_code=404, detail="Bunday idli unit topilmadi")
    words = db.query(Word).filter(Word.unit_id == unit.id).order_by(Word.id).all()
    book = db.query(Book).filter(Book.id == unit.book_id).first()
    return words, _cefr_for_number(_book_number(book.name) if book else None), unit.name


def _format_words(words) -> str:
    lines = []
    for i, w in enumerate(words[:MAX_TARGET_WORDS], 1):
        lines.append(
            f"{i}. {w.word_en} ({w.word_classes}) — uz: {w.word_uz} — "
            f"\"{w.definition}\" — e.g. \"{w.example}\""
        )
    return "\n".join(lines)


def _build_system_instruction(user, level, native, label, words) -> str:
    role = _SYSTEM_PROMPT.format(
        native=native,
        level=level,
        name=user.name or "there",
        streak=user.current_streak or 0,
    )
    ctx = (
        f"\n\nUSER: name={user.name or 'there'}, native={native}, "
        f"level={level}, streak={user.current_streak or 0}\n\n"
        f"TARGET WORDS (from \"{label}\"):\n{_format_words(words)}"
    )
    return role + ctx


def _build_contents(messages) -> list:
    # Faqat oxirgi MAX_HISTORY_MESSAGES ta xabar — prompt cheksiz o'smasin.
    contents = []
    for m in messages[-MAX_HISTORY_MESSAGES:]:
        role = "model" if m.role == "model" else "user"
        contents.append({"role": role, "parts": [{"text": m.text}]})
    # Gemini oxirgi turn "user" bo'lishini kutadi; bo'sh yoki model bilan
    # tugagan bo'lsa — AI o'zi suhbatni boshlaydigan kick qo'shamiz.
    if not contents or contents[-1]["role"] != "user":
        contents.append({"role": "user", "parts": [{"text": _GREETING_KICK}]})
    return contents


def _conversation_key(source: str, unit_id) -> str:
    """Suhbatni ajratuvchi kalit — unit kesimida alohida, sevimlilar alohida."""
    if source == "unit" and unit_id is not None:
        return f"unit:{unit_id}"
    return "favorites"


def _load_history(db: Session, user_id: int, key: str, limit: int):
    """Suhbatning oxirgi `limit` ta xabari (xronologik tartibda)."""
    rows = (
        db.query(SpeakingHistory)
        .filter(
            SpeakingHistory.user_id == user_id,
            SpeakingHistory.conversation_key == key,
        )
        .order_by(SpeakingHistory.id.desc())
        .limit(limit)
        .all()
    )
    rows.reverse()  # eng eskisi birinchi
    return rows


def _history_to_dicts(rows) -> list:
    out = []
    for r in rows:
        item = {"role": r.role, "text": r.text}
        if r.role == "model" and r.corrections:
            try:
                item["corrections"] = json.loads(r.corrections)
            except (ValueError, TypeError):
                item["corrections"] = []
        else:
            item["corrections"] = []
        out.append(item)
    return out


def _persist_turn(db: Session, user_id: int, key: str,
                  user_text: str, model_text: str, corrections) -> None:
    """Bitta turn'ni (foydalanuvchi gapi + AI javobi) saqlaydi va suhbatni
    oxirgi MAX_HISTORY_MESSAGES ta xabar bilan cheklaydi (eskisini o'chiradi).

    Xatolik bo'lsa suhbat oqimini buzmaslik uchun jimgina o'tkazib yuboriladi
    (saqlash — asosiy javobning muvaffaqiyatiga to'sqinlik qilmasligi kerak)."""
    try:
        if user_text:
            db.add(SpeakingHistory(
                user_id=user_id, conversation_key=key,
                role="user", text=user_text))
        db.add(SpeakingHistory(
            user_id=user_id, conversation_key=key, role="model",
            text=model_text or "",
            corrections=json.dumps(corrections or []),
        ))
        db.commit()

        # Eski xabarlarni tozalash — faqat oxirgi N qolsin.
        keep_ids = [
            r.id for r in db.query(SpeakingHistory.id)
            .filter(
                SpeakingHistory.user_id == user_id,
                SpeakingHistory.conversation_key == key,
            )
            .order_by(SpeakingHistory.id.desc())
            .limit(MAX_HISTORY_MESSAGES)
            .all()
        ]
        if keep_ids:
            (
                db.query(SpeakingHistory)
                .filter(
                    SpeakingHistory.user_id == user_id,
                    SpeakingHistory.conversation_key == key,
                    ~SpeakingHistory.id.in_(keep_ids),
                )
                .delete(synchronize_session=False)
            )
            db.commit()
    except Exception:
        db.rollback()


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _usage_date(payload) -> str:
    """Hisob sanasi — client mahalliy sanasi (bo'lsa), aks holda server UTC."""
    d = getattr(payload, "local_date", None)
    return d if d else _today_utc()


def _envelope(success, code, message, data):
    return jsonable_encoder(
        {"success": success, "code": code, "message": message, "data": data}
    )


def _get_or_create_usage(db: Session, user_id: int, day: str) -> AiUsage:
    """(user, day) yozuvini oladi; bo'lmasa yaratadi. Bir vaqtda kelgan
    /chat va /consume ikkalasi ham yaratmoqchi bo'lsa — unique constraint
    tufayli biri xato beradi; uni ushlab qayta o'qiymiz."""
    usage = (
        db.query(AiUsage)
        .filter(AiUsage.user_id == user_id, AiUsage.date == day)
        .first()
    )
    if usage is not None:
        return usage
    usage = AiUsage(user_id=user_id, date=day, count=0, seconds_used=0)
    db.add(usage)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        usage = (
            db.query(AiUsage)
            .filter(AiUsage.user_id == user_id, AiUsage.date == day)
            .first()
        )
    return usage


def _bump_usage(db: Session, user_id: int, day: str, elapsed: int,
                inc_count: bool) -> int:
    """`seconds_used` ni ATOMIK (SQL ifoda bilan) oshiradi va yangi qiymatni
    qaytaradi.

    MUHIM: `usage.seconds_used = old + elapsed` (Python'da o'qib-yozish) o'rniga
    SQL `seconds_used = seconds_used + :elapsed` ishlatamiz. Aks holda vaqt 0 ga
    yetgan payt bir vaqtda kelgan /chat va /consume so'rovlari bir-birining
    o'sishini ustidan yozib yuborardi (lost update) — server kam hisoblab, qaytib
    kirganda ~5s "qolgan" ko'rinardi."""
    _get_or_create_usage(db, user_id, day)
    updates = {
        AiUsage.seconds_used: func.coalesce(AiUsage.seconds_used, 0) + elapsed,
    }
    if inc_count:
        updates[AiUsage.count] = func.coalesce(AiUsage.count, 0) + 1
    (
        db.query(AiUsage)
        .filter(AiUsage.user_id == user_id, AiUsage.date == day)
        .update(updates, synchronize_session=False)
    )
    db.commit()
    row = (
        db.query(AiUsage)
        .filter(AiUsage.user_id == user_id, AiUsage.date == day)
        .first()
    )
    return int(row.seconds_used or 0) if row else 0


@speaking_router.post('/chat')
def speaking_chat(
    payload: SpeakingChatModel,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """AI speaking partnyor bilan bitta suhbat aylanasi.

    Login majburiy. Kunlik VAQT limiti (tarifga qarab) qo'llaniladi.
    """
    day = _usage_date(payload)
    limit = daily_limit_seconds(user)
    usage = (
        db.query(AiUsage)
        .filter(AiUsage.user_id == user.id, AiUsage.date == day)
        .first()
    )
    used = (usage.seconds_used or 0) if usage else 0

    # 1) Kunlik vaqt limiti (Gemini chaqirmasdan oldin tekshiramiz)
    if used >= limit:
        return _envelope(
            True, 429, "Bugungi AI suhbat vaqti tugadi.",
            _quota_data(user, used, limit, limit_reached=True),
        )

    # 2) Target so'zlar + daraja
    words, level, label = _words_and_level(db, user, payload)
    if not words:
        return _envelope(
            False, 400,
            "Suhbat uchun so'z topilmadi (unit bo'sh yoki sevimlilar yo'q).",
            None,
        )

    # 3) Prompt
    native = _LOCALE_LANG.get(payload.locale, "Uzbek")
    system = _build_system_instruction(user, level, native, label, words)
    contents = _build_contents(payload.messages)

    # 4) Gemini (tarifga mos model bilan)
    try:
        result = generate_chat(system, contents, preferred_model=model_for(user))
    except GeminiError as e:
        raise HTTPException(status_code=502, detail=f"AI xizmati xatosi: {e}")

    # 5) Faqat MUVAFFAQIYATLI javobdan keyin vaqt + hisoblagichni yangilaymiz.
    #    elapsed_seconds aldashni cheklash uchun [0, MAX_TURN_SECONDS] ga qisiladi.
    #    ATOMIK oshiramiz (lost update bo'lmasin) — pastdagi _bump_usage'ga qarang.
    elapsed = max(0, min(int(payload.elapsed_seconds or 0), MAX_TURN_SECONDS))
    used_now = _bump_usage(db, user.id, day, elapsed, inc_count=True)

    # 5.1) Suhbat tarixini saqlaymiz (unit/favorites kesimida) — qaytib kirganda
    #      foydalanuvchi shu joydan davom etadi. Faqat YANGI turn saqlanadi:
    #      oxirgi user gapi (bo'lsa) + AI javobi.
    key = _conversation_key(payload.source, payload.unit_id)
    new_user_text = ""
    if payload.messages and payload.messages[-1].role == "user":
        new_user_text = payload.messages[-1].text
    _persist_turn(db, user.id, key, new_user_text,
                  result.get("reply", ""), result.get("corrections", []))

    # 6) Javob (Gemini natijasi + tarif/vaqt meta)
    data = {
        "reply": result.get("reply", ""),
        "corrections": result.get("corrections", []),
        "target_words_used_by_user": result.get("target_words_used_by_user", []),
        "target_words_introduced": result.get("target_words_introduced", []),
        "level": level,
        "target_word_count": len(words[:MAX_TARGET_WORDS]),
    }
    data.update(_quota_data(user, used_now, limit,
                            limit_reached=used_now >= limit))
    return _envelope(True, 200, "Hammasi yaxshi", data)


@speaking_router.get('/quota')
def speaking_quota(
    local_date: str = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Foydalanuvchining bugungi qolgan AI vaqti va tarifi.

    Speaking sahifasi ochilganda ko'rsatkichni darrov ko'rsatish uchun ishlatiladi."""
    day = local_date or _today_utc()
    limit = daily_limit_seconds(user)
    usage = (
        db.query(AiUsage)
        .filter(AiUsage.user_id == user.id, AiUsage.date == day)
        .first()
    )
    used = (usage.seconds_used or 0) if usage else 0
    return _envelope(True, 200, "Hammasi yaxshi",
                     _quota_data(user, used, limit, limit_reached=used >= limit))


@speaking_router.get('/history')
def speaking_history(
    source: str = "unit",
    unit_id: int = None,
    limit: int = MAX_HISTORY_MESSAGES,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Suhbatning oxirgi xabarlari (unit/favorites kesimida).

    Speaking sahifasi ochilganda ishlatiladi — eski suhbat ko'rsatiladi va
    foydalanuvchi shu joydan davom etadi. Daraja va target so'z sonini ham
    qaytaradi (resume'da header darrov to'ldirilsin).
    """
    key = _conversation_key(source, unit_id)
    limit = max(1, min(int(limit or MAX_HISTORY_MESSAGES), MAX_HISTORY_MESSAGES))
    rows = _load_history(db, user.id, key, limit)
    messages = _history_to_dicts(rows)

    level = ""
    target_word_count = 0
    try:
        shim = SimpleNamespace(source=source, unit_id=unit_id)
        words, level, _label = _words_and_level(db, user, shim)
        target_word_count = len(words[:MAX_TARGET_WORDS])
    except HTTPException:
        pass

    return _envelope(True, 200, "Hammasi yaxshi", {
        "messages": messages,
        "level": level,
        "target_word_count": target_word_count,
    })


@speaking_router.post('/consume')
def speaking_consume(
    payload: SpeakingConsumeModel,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Suhbat o'tkazmasdan sarflangan AI vaqtni qayd etadi.

    Vaqt o'zi tugaganda (xabar yubormay) yoki sahifadan chiqishda client shu
    yerga oxirgi yuborilmagan soniyalarni yuboradi. Aks holda server `seconds_used`
    eski qiymatda qoladi va qaytib kirganda vaqt noto'g'ri (masalan 5s) ko'rinadi.
    elapsed [0, MAX_TURN_SECONDS] ga qisiladi (aldash himoyasi)."""
    day = _usage_date(payload)  # chat bilan bir xil kun (row) — local_date yoki UTC
    limit = daily_limit_seconds(user)
    elapsed = max(0, min(int(payload.elapsed_seconds or 0), MAX_TURN_SECONDS))
    # ATOMIK oshiramiz — /chat bilan bir vaqtda kelsa ham yo'qolmasin.
    used = _bump_usage(db, user.id, day, elapsed, inc_count=False)
    return _envelope(True, 200, "Hammasi yaxshi",
                     _quota_data(user, used, limit, limit_reached=used >= limit))


def _user_brief(u: User) -> dict:
    """Admin paneli uchun foydalanuvchi qisqa ma'lumoti."""
    exp = u.tier_expires_at
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "picture": u.picture,
        "tier": effective_tier(u),
        "tier_raw": u.tier or "free",
        "tier_expires_at": exp.isoformat() if exp else None,
    }


@speaking_router.get('/admin/users')
def admin_find_users(
    search: str = "",
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_secret),
):
    """Admin: email yoki ism bo'yicha foydalanuvchilarni qidiradi (tarif berish uchun)."""
    q = db.query(User)
    s = (search or "").strip()
    if s:
        like = f"%{s}%"
        q = q.filter((User.email.ilike(like)) | (User.name.ilike(like)))
    users = q.order_by(User.id.desc()).limit(30).all()
    return _envelope(True, 200, "Hammasi yaxshi",
                     [_user_brief(u) for u in users])


@speaking_router.post('/admin/set-tier')
def admin_set_tier(
    tier: str,
    user_id: int = None,
    email: str = None,
    days: int = 30,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_secret),
):
    """Admin foydalanuvchiga tarif beradi (to'lov ulanmaguncha qo'lda boshqaruv).

    `user_id` YOKI `email` bilan topiladi. tier: "free" | "pro" | "premium".
    days — obuna muddati. Muddat tugagach backend avtomatik "free"ga qaytaradi
    (effective_tier) — alohida cancel kerak emas.
    """
    if tier not in TIER_DAILY_SECONDS:
        raise HTTPException(status_code=400, detail="Noto'g'ri tarif")

    target = None
    if user_id is not None:
        target = db.query(User).filter(User.id == user_id).first()
    elif email:
        target = db.query(User).filter(User.email == email.strip()).first()
    if target is None:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    target.tier = tier
    if tier == "free":
        target.tier_expires_at = None
    else:
        target.tier_expires_at = datetime.now(timezone.utc) + timedelta(days=days)
    db.commit()
    return _envelope(True, 200, "Tarif yangilandi", _user_brief(target))


def _quota_data(user, used, limit, limit_reached):
    used = max(0, int(used))
    return {
        "tier": effective_tier(user),
        "seconds_used": used,
        "daily_limit_seconds": limit,
        "seconds_left": max(0, limit - used),
        "limit_reached": bool(limit_reached),
        # Barcha tariflar limiti — app'da "tarif oshirish" ekranida ko'rsatish uchun.
        "tier_limits": TIER_DAILY_SECONDS,
    }
