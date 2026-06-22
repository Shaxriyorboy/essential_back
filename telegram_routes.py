"""Telegram bot — Pro/Premium tarif arizalari (to'lov in-app emas).

Ishlash printsipi (WEBHOOK, polling emas — alohida process kerak emas):
  1. Foydalanuvchi botga /start beradi → tarif (Pro/Premium) tugmalari chiqadi.
  2. Tarif tanlaydi → bot "ilovaga kirgan emailingizni yuboring" deydi.
  3. Email yuboradi → ariza ADMIN Telegramiga keladi (TELEGRAM_ADMIN_CHAT_ID),
     ariza ostida "✅ Pro berish" / "❌ Rad etish" tugmalari bilan.
  4. Admin "✅ ... berish" tugmasini bosadi → o'sha email egasiga tarif DARROV
     beriladi (DB'da tier + tier_expires_at yangilanadi) — essential_admin ochish shart emas.

Kerakli env (Render → Environment):
  TELEGRAM_BOT_TOKEN       — @BotFather token
  TELEGRAM_ADMIN_CHAT_ID   — arizalar keladigan chat id (@userinfobot beradi)
  TELEGRAM_WEBHOOK_SECRET  — (ixtiyoriy) Telegram so'rovlarini tasdiqlash uchun maxfiy satr

Webhook avtomatik ro'yxatdan o'tadi (startup'da, RENDER_EXTERNAL_URL bo'lsa).
Qo'lda: POST /telegram/set-webhook?url=https://...  (X-Admin-Secret header bilan).
"""
import os
import re
from datetime import datetime, timedelta, timezone

import requests
from fastapi import APIRouter, Header, HTTPException, Request

from database import SessionLocal
from models import User
from tiers import TIER_DAILY_SECONDS

telegram_router = APIRouter(prefix="/telegram")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
# Arizalar keladigan admin chat id. Env bilan override qilish mumkin.
ADMIN_CHAT_ID = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "1463491021")
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ────────────────────────────────────────────────────────────────────────────
# TARIFLAR — narx/muddatni shu yerda o'zgartiring (deploy qiling, app yangilanmaydi).
# days — obuna muddati (kun). Tugagach backend avtomatik "free"ga qaytaradi.
# ────────────────────────────────────────────────────────────────────────────
TARIFFS = {
    "pro": {"title": "Pro", "days": 30, "price": "19 900 so'm", "perks": "Kuniga 20 daqiqa AI suhbat"},
    "premium": {"title": "Premium", "days": 30, "price": "39 900 so'm", "perks": "Kuniga 30 daqiqa + yuqori sifatli model"},
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Foydalanuvchi tarif tanlagach, email kutilayotganini eslab turish (qisqa muddatli).
# Render restart bo'lsa yo'qoladi — zarari yo'q, foydalanuvchi qayta tanlaydi.
_pending_tier = {}  # chat_id(str) -> tier(str)


# ───────────────────────── Telegram API yordamchilari ──────────────────────
def _tg(method: str, payload: dict) -> dict:
    if not BOT_TOKEN:
        return {}
    try:
        r = requests.post(f"{API}/{method}", json=payload, timeout=15)
        return r.json()
    except requests.RequestException:
        return {}


def _send(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
               "disable_web_page_preview": True}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return _tg("sendMessage", payload)


def _answer_callback(callback_id, text=None):
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    _tg("answerCallbackQuery", payload)


def _edit_text(chat_id, message_id, text):
    _tg("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                            "text": text, "parse_mode": "HTML",
                            "disable_web_page_preview": True})


# ───────────────────────────── Matnlar / klaviatura ────────────────────────
def _welcome_text() -> str:
    lines = [
        "👋 <b>Essential</b> — AI Speaking Partner.",
        "",
        "AI bilan ingliz tilida suhbatlashish vaqtini oshirish uchun tarif tanlang:",
        "",
    ]
    for key in ("pro", "premium"):
        t = TARIFFS[key]
        lines.append(f"• <b>{t['title']}</b> — {t['price']} / {t['days']} kun")
        lines.append(f"   {t['perks']}")
    lines.append("")
    lines.append("Tarifni tanlang ⤵️")
    return "\n".join(lines)


def _tariff_keyboard():
    row = [{"text": f"{TARIFFS[k]['title']} — {TARIFFS[k]['price']}",
            "callback_data": f"tier:{k}"} for k in ("pro", "premium")]
    return {"inline_keyboard": [row]}


def _grant_keyboard(tier: str, days: int, email: str):
    """Admin uchun: bir bosishda tarif berish/rad etish tugmalari.

    callback_data 64 bayt bilan cheklangan — email juda uzun bo'lsa tugma
    qo'yilmaydi (admin essential_admin orqali qo'lda beradi)."""
    data = f"g|{tier}|{days}|{email}"
    if len(data.encode()) > 60:
        return None
    return {"inline_keyboard": [[
        {"text": f"✅ {TARIFFS[tier]['title']} {days} kun berish", "callback_data": data},
        {"text": "❌ Rad etish", "callback_data": "x|0"},
    ]]}


# ──────────────────────────── Update handlerlari ───────────────────────────
def _handle_message(msg: dict):
    chat = msg.get("chat", {})
    chat_id = str(chat.get("id", ""))
    text = (msg.get("text") or "").strip()
    if not chat_id:
        return

    if text.startswith("/start") or text.lower() in ("/help", "menu", "tarif", "tariff"):
        _pending_tier.pop(chat_id, None)
        _send(chat_id, _welcome_text(), reply_markup=_tariff_keyboard())
        return

    # Email kutilayaptimi?
    tier = _pending_tier.get(chat_id)
    if tier:
        if not EMAIL_RE.match(text):
            _send(chat_id, "❌ Bu email ko'rinmadi. Iltimos ilovaga kirgan "
                           "emailingizni to'liq yuboring (masalan: <code>ism@gmail.com</code>).")
            return
        _pending_tier.pop(chat_id, None)
        _forward_application(msg, tier, text.lower())
        _send(chat_id, "✅ Arizangiz qabul qilindi! Tez orada tarifingiz faollashtiriladi. "
                       "Rahmat 🙌")
        return

    # Hech narsa kutilmayapti
    _send(chat_id, "Boshlash uchun /start bosing yoki tarif tanlang.",
          reply_markup=_tariff_keyboard())


def _forward_application(user_msg: dict, tier: str, email: str):
    """Arizani ADMIN Telegramiga yuboradi (grant tugmalari bilan)."""
    if not ADMIN_CHAT_ID:
        return
    frm = user_msg.get("from", {})
    uname = frm.get("username")
    name = " ".join(filter(None, [frm.get("first_name"), frm.get("last_name")])) or "—"
    uid = frm.get("id", "—")
    t = TARIFFS.get(tier, {})
    days = t.get("days", 30)
    tg_line = f"@{uname}" if uname else f"id {uid}"
    text = (
        "📩 <b>Yangi tarif ariza</b>\n"
        f"Tarif: <b>{t.get('title', tier)}</b> ({days} kun)\n"
        f"Email: <code>{email}</code>\n"
        f"Telegram: {tg_line} ({name})\n"
        "\nQuyidagi tugma orqali darrov bering yoki essential_admin'da qo'lda."
    )
    _send(ADMIN_CHAT_ID, text, reply_markup=_grant_keyboard(tier, days, email))


def _handle_callback(cb: dict):
    cb_id = cb.get("id")
    data = cb.get("data") or ""
    msg = cb.get("message", {})
    chat_id = str(msg.get("chat", {}).get("id", ""))
    from_id = str(cb.get("from", {}).get("id", ""))
    message_id = msg.get("message_id")

    # Foydalanuvchi tarif tanladi
    if data.startswith("tier:"):
        tier = data.split(":", 1)[1]
        if tier not in TARIFFS:
            _answer_callback(cb_id, "Noto'g'ri tarif")
            return
        _pending_tier[chat_id] = tier
        _answer_callback(cb_id)
        _send(chat_id, f"<b>{TARIFFS[tier]['title']}</b> tanlandi ✅\n\n"
                       "Iltimos <b>ilovaga kirgan emailingizni</b> yuboring "
                       "(Google/Apple bilan kirgan email). Shu email orqali tarif beriladi.")
        return

    # Admin: rad etish
    if data == "x|0":
        if from_id != str(ADMIN_CHAT_ID):
            _answer_callback(cb_id, "Faqat admin")
            return
        _answer_callback(cb_id, "Rad etildi")
        _edit_text(chat_id, message_id, (msg.get("text") or "") + "\n\n❌ <b>Rad etildi</b>")
        return

    # Admin: tarif berish  g|tier|days|email
    if data.startswith("g|"):
        if from_id != str(ADMIN_CHAT_ID):
            _answer_callback(cb_id, "Faqat admin")
            return
        try:
            _, tier, days_s, email = data.split("|", 3)
            days = int(days_s)
        except ValueError:
            _answer_callback(cb_id, "Xato format")
            return
        ok, info = _grant_tier(email, tier, days)
        _answer_callback(cb_id, info)
        suffix = (f"\n\n✅ <b>{TARIFFS.get(tier, {}).get('title', tier)} berildi</b> "
                  f"({email})" if ok else f"\n\n⚠️ {info}")
        _edit_text(chat_id, message_id, (msg.get("text") or "") + suffix)
        return

    _answer_callback(cb_id)


def _grant_tier(email: str, tier: str, days: int):
    """Email egasiga tarif beradi. (ok, xabar) qaytaradi."""
    if tier not in TIER_DAILY_SECONDS:
        return False, "Noto'g'ri tarif"
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email.ilike(email.strip())).first()
        if user is None:
            return False, "Bu email bilan foydalanuvchi topilmadi"
        user.tier = tier
        user.tier_expires_at = datetime.now(timezone.utc) + timedelta(days=days)
        db.commit()
        return True, f"{tier} berildi"
    finally:
        db.close()


# ──────────────────────────────── Endpointlar ──────────────────────────────
@telegram_router.post("/webhook")
async def telegram_webhook(request: Request,
                           x_telegram_bot_api_secret_token: str = Header(default="")):
    # Maxfiy token sozlangan bo'lsa — tekshiramiz (begona so'rovlarni rad etamiz)
    if WEBHOOK_SECRET and x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="forbidden")
    update = await request.json()
    try:
        if "message" in update:
            _handle_message(update["message"])
        elif "callback_query" in update:
            _handle_callback(update["callback_query"])
    except Exception:
        # Webhook har doim 200 qaytarishi kerak — aks holda Telegram qayta uradi.
        pass
    return {"ok": True}


def _public_base_url() -> str:
    """Hosting bergan public URL. Render -> RENDER_EXTERNAL_URL (to'liq URL),
    Railway -> RAILWAY_PUBLIC_DOMAIN (faqat domen, https:// qo'shamiz).
    PUBLIC_BASE_URL bilan qo'lda ham berish mumkin."""
    base = os.environ.get("PUBLIC_BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL")
    if base:
        return base
    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
    if domain:
        return domain if domain.startswith("http") else f"https://{domain}"
    return ""


@telegram_router.post("/set-webhook")
def set_webhook(url: str = None, x_admin_secret: str = Header(default="")):
    """Webhook URL'ni qo'lda ro'yxatdan o'tkazadi (X-Admin-Secret bilan himoyalangan).

    url berilmasa hosting bergan public URL (Render/Railway) ishlatiladi."""
    if not ADMIN_SECRET or x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Admin huquqi kerak")
    base = url or _public_base_url()
    if not base:
        raise HTTPException(status_code=400, detail="url yo'q (public URL topilmadi)")
    hook = base.rstrip("/") + "/telegram/webhook"
    payload = {"url": hook, "allowed_updates": ["message", "callback_query"]}
    if WEBHOOK_SECRET:
        payload["secret_token"] = WEBHOOK_SECRET
    return _tg("setWebhook", payload)


def ensure_webhook():
    """Startup'da webhook'ni avtomatik ro'yxatdan o'tkazadi (Render/Railway)."""
    base = _public_base_url()
    if not (BOT_TOKEN and base):
        return
    hook = base.rstrip("/") + "/telegram/webhook"
    payload = {"url": hook, "allowed_updates": ["message", "callback_query"]}
    if WEBHOOK_SECRET:
        payload["secret_token"] = WEBHOOK_SECRET
    _tg("setWebhook", payload)
