"""AI Speaking tarif (obuna) konfiguratsiyasi.

Kunlik vaqt limiti (soniya) har tarif uchun. Hozirgi qiymatlar TAXMINIY —
narx/vaqt aniqlanganda shu yerni (yoki env'ni) o'zgartiring, deploy qiling.
App yangilanmaydi — limit backend'dan keladi.

Env bilan override qilish mumkin: TIER_FREE_SECONDS, TIER_PRO_SECONDS,
TIER_PREMIUM_SECONDS.
"""
import os
from datetime import datetime, timezone


def _sec(env_name: str, default: int) -> int:
    try:
        return int(os.environ.get(env_name, default))
    except (TypeError, ValueError):
        return default


# Kunlik AI speaking vaqt limiti (soniya)
TIER_DAILY_SECONDS = {
    "free": _sec("TIER_FREE_SECONDS", 5 * 60),       # 5 daqiqa
    "pro": _sec("TIER_PRO_SECONDS", 20 * 60),         # 20 daqiqa
    "premium": _sec("TIER_PREMIUM_SECONDS", 30 * 60),  # 30 daqiqa
}

# Har tarif qaysi Gemini modeldan foydalanadi (sifat farqi).
TIER_MODEL = {
    "free": os.environ.get("TIER_FREE_MODEL", "gemini-2.5-flash-lite"),
    "pro": os.environ.get("TIER_PRO_MODEL", "gemini-2.5-flash-lite"),
    "premium": os.environ.get("TIER_PREMIUM_MODEL", "gemini-2.5-flash"),
}


def effective_tier(user) -> str:
    """Foydalanuvchining AMALDAGI tarifi.

    Obuna muddati tugagan bo'lsa "free" qaytaradi (DB'ni o'zgartirmaydi —
    bu faqat o'qish; tozalashni alohida joy qiladi)."""
    tier = (getattr(user, "tier", None) or "free")
    if tier == "free":
        return "free"
    expires = getattr(user, "tier_expires_at", None)
    if expires is not None:
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            return "free"  # muddati tugagan
    return tier if tier in TIER_DAILY_SECONDS else "free"


def daily_limit_seconds(user) -> int:
    return TIER_DAILY_SECONDS.get(effective_tier(user), TIER_DAILY_SECONDS["free"])


def model_for(user) -> str:
    return TIER_MODEL.get(effective_tier(user), TIER_MODEL["free"])
