"""Gemini (Google AI Studio) bilan ishlash — AI speaking partnyor uchun.

Bepul tier: gemini-2.5-flash (~1500 so'rov/kun, API kalit bo'yicha UMUMIY).
Env o'zgaruvchilari:
- GEMINI_API_KEY  — Google AI Studio'dan olingan kalit (majburiy)
- GEMINI_MODEL    — model nomi (default: gemini-2.5-flash)

Yangi paket qo'shmaymiz — mavjud `requests` orqali REST API'ni chaqiramiz.
"""
import json
import os
import time

import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# flash-lite — bepul tier limiti kengroq va arzon (qisqa suhbat javoblari uchun yetarli).
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

# Bepul tier beqaror (503 "high demand" / 429 "quota") bo'lgani uchun bir nechta
# modelni navbatma-navbat sinaymiz — biri band bo'lsa, keyingisiga o'tamiz.
_FALLBACK_MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
]
# Shu statuslarда qayta urinamiz / boshqa modelga o'tamiz (vaqtinchalik).
_RETRYABLE = {429, 500, 503}
_ROUNDS = 2  # barcha modellardan o'tib bo'lgach yana shuncha marta takror


def _models_to_try(preferred_model=None):
    """Afzal model (tarifга qarab) + asosiy + fallback'lar (takrorlanmasdan)."""
    ordered, seen = [], set()
    for m in [preferred_model, GEMINI_MODEL] + _FALLBACK_MODELS:
        if m and m not in seen:
            seen.add(m)
            ordered.append(m)
    return ordered

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


def generate_chat(system_instruction: str, contents: list, preferred_model=None) -> dict:
    """Gemini'ga structured-output bilan so'rov yuboradi va tayyor dict qaytaradi.

    system_instruction — rol + dynamic context (USER + TARGET WORDS).
    contents — [{"role": "user"|"model", "parts": [{"text": ...}]}] suhbat tarixi.

    Qaytadi: {reply, corrections, target_words_used_by_user, target_words_introduced}.
    Xato bo'lsa GeminiError ko'taradi.
    """
    if not GEMINI_API_KEY:
        raise GeminiError("GEMINI_API_KEY o'rnatilmagan")

    base_gen_config = {
        "temperature": 0.8,
        "responseMimeType": "application/json",
        "responseSchema": _RESPONSE_SCHEMA,
    }

    def _body_for(model):
        gen = dict(base_gen_config)
        # "Thinking"ni o'chiramiz — speaking suhbat uchun kerak emas. Output
        # tokenni (ayniqsa premium=2.5-flash, $2.50/1M) keskin kamaytiradi va
        # javobni tezlashtiradi. FAQAT 2.5 modellar qo'llaydi — 2.0'ga yuborilsa
        # 400 beradi, shuning uchun shartli qo'shamiz.
        if model.startswith("gemini-2.5"):
            gen["thinkingConfig"] = {"thinkingBudget": 0}
        return {
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": contents,
            "generationConfig": gen,
        }

    models = _models_to_try(preferred_model)
    last_err = "urinish bo'lmadi"

    for round_idx in range(_ROUNDS):
        for model in models:
            try:
                resp = requests.post(
                    _ENDPOINT.format(model=model),
                    params={"key": GEMINI_API_KEY},
                    json=_body_for(model),
                    timeout=30,
                )
            except requests.RequestException as e:
                last_err = f"{model}: ulanib bo'lmadi: {e}"
                continue

            if resp.status_code == 200:
                return _parse(resp.json())

            last_err = f"{model} {resp.status_code}: {resp.text[:200]}"
            # 400/401/403/404 — sozlama/kalit xatosi, qayta urinishdan foyda yo'q.
            if resp.status_code not in _RETRYABLE:
                raise GeminiError(last_err)
            # aks holda keyingi modelga o'tamiz (band/quota — vaqtinchalik)

        # Bir aylanada hammasi band bo'lsa, qisqa kutib yana urinamiz.
        if round_idx + 1 < _ROUNDS:
            time.sleep(1.5)

    raise GeminiError(last_err)


def _parse(data: dict) -> dict:
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
