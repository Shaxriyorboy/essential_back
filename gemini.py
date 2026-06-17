"""Gemini (Google AI Studio) bilan ishlash — AI speaking partnyor uchun.

Bepul tier: gemini-2.5-flash (~1500 so'rov/kun, API kalit bo'yicha UMUMIY).
Env o'zgaruvchilari:
- GEMINI_API_KEY  — Google AI Studio'dan olingan kalit (majburiy)
- GEMINI_MODEL    — model nomi (default: gemini-2.5-flash)

Yangi paket qo'shmaymiz — mavjud `requests` orqali REST API'ni chaqiramiz.
"""
import json
import os

import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

# Structured output sxemasi — Gemini javobni AYNAN shu shaklda qaytaradi.
# (SPEAKING_PARTNER_SPEC.md dagi "Response" bilan bir xil.)
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "corrections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "original": {"type": "string"},
                    "fixed": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["original", "fixed", "note"],
            },
        },
        "target_words_used_by_user": {"type": "array", "items": {"type": "string"}},
        "target_words_introduced": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "reply",
        "corrections",
        "target_words_used_by_user",
        "target_words_introduced",
    ],
}


class GeminiError(Exception):
    """Gemini bilan ishlashda yuzaga kelgan xato (kalit yo'q, tarmoq, yaroqsiz javob)."""


def generate_chat(system_instruction: str, contents: list) -> dict:
    """Gemini'ga structured-output bilan so'rov yuboradi va tayyor dict qaytaradi.

    system_instruction — rol + dynamic context (USER + TARGET WORDS).
    contents — [{"role": "user"|"model", "parts": [{"text": ...}]}] suhbat tarixi.

    Qaytadi: {reply, corrections, target_words_used_by_user, target_words_introduced}.
    Xato bo'lsa GeminiError ko'taradi.
    """
    if not GEMINI_API_KEY:
        raise GeminiError("GEMINI_API_KEY o'rnatilmagan")

    body = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.8,
            "responseMimeType": "application/json",
            "responseSchema": _RESPONSE_SCHEMA,
        },
    }

    try:
        resp = requests.post(
            _ENDPOINT.format(model=GEMINI_MODEL),
            params={"key": GEMINI_API_KEY},
            json=body,
            timeout=30,
        )
    except requests.RequestException as e:
        raise GeminiError(f"Gemini'ga ulanib bo'lmadi: {e}")

    if resp.status_code != 200:
        raise GeminiError(f"Gemini xatosi {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        # Masalan safety bilan bloklangan yoki bo'sh javob
        raise GeminiError(f"Gemini javobi kutilmagan shaklda: {json.dumps(data)[:300]}")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # responseMimeType=json bo'lgani uchun bunga deyarli tushmaymiz
        raise GeminiError(f"Gemini JSON javobini o'qib bo'lmadi: {text[:300]}")
