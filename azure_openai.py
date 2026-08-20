"""Azure OpenAI (gpt-4.1-mini) bilan ishlash — AI speaking partnyor uchun.

`gemini.py` bilan BIR XIL interfeys: `generate_chat(system, contents)` -> dict.
Shu sababli `speaking_routes` deyarli o'zgarmaydi — provayder `llm.py` orqali
env bilan tanlanadi (Azure YOKI Gemini).

Yangi og'ir kutubxona qo'shmaymiz — mavjud `requests` orqali REST chaqiramiz.

Env (Render):
- AZURE_OPENAI_ENDPOINT    — masalan https://essential-openai.openai.azure.com/
- AZURE_OPENAI_KEY         — resource kaliti (KEY 1)
- AZURE_OPENAI_DEPLOYMENT  — deployment nomi (masalan gpt-4.1-mini)
- AZURE_OPENAI_API_VERSION — ixtiyoriy (default 2025-01-01-preview)
"""
import json
import os
import time

import requests


class AzureOpenAIError(Exception):
    """Azure OpenAI bilan ishlashda xato (kalit yo'q, tarmoq, yaroqsiz javob)."""


def _endpoint() -> str:
    return os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")


def _key() -> str:
    return os.environ.get("AZURE_OPENAI_KEY", "")


def _deployment() -> str:
    return os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini")


def _api_version() -> str:
    return os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")


def is_configured() -> bool:
    return bool(_endpoint() and _key())


# Shu statuslarda qayta urinamiz (vaqtinchalik).
_RETRYABLE = {429, 500, 503}
_MAX_RETRIES = 3

# OpenAI "strict" structured output talabi: har `object` da
# `additionalProperties: false` VA hamma property `required` bo'lishi shart.
# (Gemini sxemasidan farqi shu.)
_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "reply": {"type": "string"},
        "corrections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
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


def _to_openai_messages(system_instruction: str, contents: list) -> list:
    """Gemini formatidagi `contents` ni OpenAI `messages` ga o'giradi.

    Gemini:  [{"role":"user"|"model","parts":[{"text":...}]}]
    OpenAI:  [{"role":"system","content":...}, {"role":"user"|"assistant","content":...}]
    """
    messages = [{"role": "system", "content": system_instruction}]
    for c in contents:
        role = c.get("role", "user")
        if role == "model":
            role = "assistant"
        parts = c.get("parts") or []
        text = " ".join(
            p.get("text", "") for p in parts if isinstance(p, dict)
        ).strip()
        messages.append({"role": role, "content": text})
    return messages


def generate_chat(system_instruction: str, contents: list, preferred_model=None) -> dict:
    """Azure OpenAI'ga structured-output bilan so'rov yuboradi.

    `preferred_model` E'TIBORGA OLINMAYDI — Azure'da model = DEPLOYMENT nomi
    (env'dan olinadi). Tariflar uchun alohida deployment qo'shilsa, shu yerda
    kengaytiriladi.

    Qaytadi: {reply, corrections, target_words_used_by_user,
              target_words_introduced}. Xato bo'lsa AzureOpenAIError.
    """
    if not is_configured():
        raise AzureOpenAIError("AZURE_OPENAI_ENDPOINT yoki AZURE_OPENAI_KEY o'rnatilmagan")

    url = (
        f"{_endpoint()}/openai/deployments/{_deployment()}"
        f"/chat/completions?api-version={_api_version()}"
    )
    body = {
        "messages": _to_openai_messages(system_instruction, contents),
        "temperature": 0.8,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "speaking_reply",
                "strict": True,
                "schema": _RESPONSE_SCHEMA,
            },
        },
    }

    last_err = "urinish bo'lmadi"
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.post(
                url,
                headers={"api-key": _key(), "Content-Type": "application/json"},
                data=json.dumps(body),
                timeout=30,
            )
        except requests.RequestException as e:
            last_err = f"ulanib bo'lmadi: {e}"
            time.sleep(1.0)
            continue

        if resp.status_code == 200:
            return _parse(resp.json())

        last_err = f"{resp.status_code}: {resp.text[:200]}"
        # 400/401/404 — sozlama/kalit xatosi, qayta urinishdan foyda yo'q.
        if resp.status_code not in _RETRYABLE:
            raise AzureOpenAIError(last_err)
        time.sleep(1.5)

    raise AzureOpenAIError(last_err)


def _parse(data: dict) -> dict:
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise AzureOpenAIError(
            f"Azure javobi kutilmagan shaklda: {json.dumps(data)[:300]}")
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        raise AzureOpenAIError(f"Azure JSON javobini o'qib bo'lmadi: {str(text)[:300]}")
