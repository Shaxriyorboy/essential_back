"""AI Speaking Partner — `POST /speaking/chat`.

Dizayn hujjati: essential ilovasi repo'sidagi SPEAKING_PARTNER_SPEC.md.

Context (system prompt + USER + TARGET WORDS) SHU YERDA quriladi (app emas) —
shunda promptni app yangilamasdan, faqat backend deploy qilib o'zgartirsa bo'ladi.
"""
import os
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from gemini import GeminiError, generate_chat
from models import AiUsage, Book, Unit, User, UserFavorite, Word
from schemes import SpeakingChatModel

speaking_router = APIRouter(prefix='/speaking')

# Bepul Gemini kvotasini (API kalit bo'yicha umumiy ~1500/kun) himoya qilish uchun
# har foydalanuvchiga kunlik xabar limiti. Render'da AI_DAILY_LIMIT bilan sozlanadi.
AI_DAILY_LIMIT = int(os.environ.get("AI_DAILY_LIMIT", "30"))

# Promptni juda kattalashtirib yubormaslik uchun target so'zlar soni cheklanadi.
MAX_TARGET_WORDS = 40

_CEFR = {1: "A1", 2: "A2", 3: "B1", 4: "B2", 5: "C1", 6: "C2"}
_LOCALE_LANG = {"uz": "Uzbek", "ru": "Russian", "en": "English"}

# Sessiya yangi ochilganda (foydalanuvchi hali gapirmagan) AI o'zi boshlashi uchun.
_GREETING_KICK = (
    "(The user just opened the session and hasn't spoken yet. Greet them warmly "
    "in English and start the conversation, naturally using one target word.)"
)

_SYSTEM_PROMPT = (
    "You are \"Essi\", a warm, patient English speaking partner inside a "
    "vocabulary-learning app. The user is a {native}-speaking English learner at "
    "CEFR level {level}. Hold a natural, encouraging conversation that helps them "
    "practice English — especially the TARGET WORDS below.\n\n"
    "Calibrate your vocabulary and grammar to {level}:\n"
    "- A1/A2: very simple words, short present-tense sentences, speak slowly.\n"
    "- B1/B2: everyday fluent language, introduce some idioms.\n"
    "- C1/C2: rich, natural, native-like speech.\n"
    "Still ADAPT: if the user is clearly stronger or weaker than {level}, match them.\n\n"
    "Rules:\n"
    "- Keep every reply SHORT: 1-3 sentences. It is a spoken back-and-forth (it may "
    "be read aloud by text-to-speech), not an essay. Always end with a simple "
    "follow-up question to keep the conversation going.\n"
    "- Naturally weave in 1-2 TARGET WORDS per reply and steer topics so the user "
    "gets a chance to use them. Never force more than two.\n"
    "- Do NOT break the flow to correct mistakes. Put grammar/word-choice fixes in "
    "the \"corrections\" field with a short, kind note written in {native}.\n"
    "- If the user is stuck, briefly explain a word in {native}, then return to English.\n"
    "- \"reply\" must be clean human speech — no lists, no markdown, no emoji."
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
    role = _SYSTEM_PROMPT.format(native=native, level=level)
    ctx = (
        f"\n\nUSER: name={user.name or 'there'}, native={native}, "
        f"level={level}, streak={user.current_streak or 0}\n\n"
        f"TARGET WORDS (from \"{label}\"):\n{_format_words(words)}"
    )
    return role + ctx


def _build_contents(messages) -> list:
    contents = []
    for m in messages:
        role = "model" if m.role == "model" else "user"
        contents.append({"role": role, "parts": [{"text": m.text}]})
    # Gemini oxirgi turn "user" bo'lishini kutadi; bo'sh yoki model bilan
    # tugagan bo'lsa — AI o'zi suhbatni boshlaydigan kick qo'shamiz.
    if not contents or contents[-1]["role"] != "user":
        contents.append({"role": "user", "parts": [{"text": _GREETING_KICK}]})
    return contents


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _envelope(success, code, message, data):
    return jsonable_encoder(
        {"success": success, "code": code, "message": message, "data": data}
    )


@speaking_router.post('/chat')
def speaking_chat(
    payload: SpeakingChatModel,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """AI speaking partnyor bilan bitta suhbat aylanasi.

    Login majburiy. Kunlik limit (per-user) bepul Gemini kvotasini himoya qiladi.
    """
    today = _today_utc()
    usage = (
        db.query(AiUsage)
        .filter(AiUsage.user_id == user.id, AiUsage.date == today)
        .first()
    )
    used = usage.count if usage else 0

    # 1) Kunlik limit (Gemini chaqirmasdan oldin tekshiramiz — kvota tejaladi)
    if used >= AI_DAILY_LIMIT:
        return _envelope(
            True, 429, "Bugungi AI suhbat limiti tugadi. Ertaga davom eting.",
            {"limit_reached": True, "daily_used": used, "daily_limit": AI_DAILY_LIMIT},
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

    # 4) Gemini
    try:
        result = generate_chat(system, contents)
    except GeminiError as e:
        raise HTTPException(status_code=502, detail=f"AI xizmati xatosi: {e}")

    # 5) Faqat MUVAFFAQIYATLI javobdan keyin hisoblagichni oshiramiz
    if usage is None:
        usage = AiUsage(user_id=user.id, date=today, count=0)
        db.add(usage)
    usage.count = (usage.count or 0) + 1
    db.commit()

    # 6) Javob (Gemini natijasi + meta)
    return _envelope(True, 200, "Hammasi yaxshi", {
        "reply": result.get("reply", ""),
        "corrections": result.get("corrections", []),
        "target_words_used_by_user": result.get("target_words_used_by_user", []),
        "target_words_introduced": result.get("target_words_introduced", []),
        "level": level,
        "daily_used": usage.count,
        "daily_limit": AI_DAILY_LIMIT,
    })
