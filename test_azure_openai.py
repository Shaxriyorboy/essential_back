"""Azure OpenAI provayderi (azure_openai.py) — HTTP MOCK bilan.

Haqiqiy Azure chaqirilmaydi: `requests.post` almashtiriladi. Maqsad — message
konvertatsiyasi (Gemini format -> OpenAI), URL/deployment, structured-output
so'rovi va javob parslashni tekshirish.

Ishga tushirish:  ./venv/bin/python test_azure_openai.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["AZURE_OPENAI_ENDPOINT"] = "https://essential-openai.openai.azure.com/"
os.environ["AZURE_OPENAI_KEY"] = "test-key-123"
os.environ["AZURE_OPENAI_DEPLOYMENT"] = "gpt-4.1-mini"
os.environ["AZURE_OPENAI_API_VERSION"] = "2025-01-01-preview"

import azure_openai  # noqa: E402
import llm  # noqa: E402

FAIL = []


def check(label, cond, detail=""):
    print(("  OK   " if cond else "  XATO ") + label
          + ("" if cond else f"  -> {detail}"))
    if not cond:
        FAIL.append(label)


# --- Soxta requests.post -----------------------------------------------------
class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


_captured = {}


def fake_post(url, headers=None, data=None, timeout=None):
    _captured["url"] = url
    _captured["headers"] = headers
    _captured["body"] = json.loads(data)
    # Gemini/OpenAI javob shakli: choices[0].message.content = JSON matn
    content = json.dumps({
        "reply": "Great, keep going!",
        "corrections": [{"original": "I is", "fixed": "I am", "note": "to be"}],
        "target_words_used_by_user": ["brave"],
        "target_words_introduced": [],
    })
    return _Resp(200, {"choices": [{"message": {"content": content}}]})


azure_openai.requests.post = fake_post

# --- 1. is_configured -------------------------------------------------------
print("1) Konfiguratsiya")
check("is_configured True (env bor)", azure_openai.is_configured() is True)

# --- 2. generate_chat: konvertatsiya + parslash -----------------------------
print("\n2) generate_chat — message konvertatsiyasi va javob")
system = "You are a tutor. TARGET WORDS: brave"
contents = [
    {"role": "user", "parts": [{"text": "I is brave"}]},
    {"role": "model", "parts": [{"text": "Nice!"}]},
    {"role": "user", "parts": [{"text": "yes"}]},
]
res = azure_openai.generate_chat(system, contents, preferred_model="ignored")

check("reply parslandi", res["reply"] == "Great, keep going!", res.get("reply"))
check("correction parslandi", len(res["corrections"]) == 1, res.get("corrections"))
check("used words parslandi", res["target_words_used_by_user"] == ["brave"], res)

# URL to'g'ri (deployment + api-version)
check("URL deployment o'z ichida", "/deployments/gpt-4.1-mini/" in _captured["url"],
      _captured["url"])
check("URL api-version", "api-version=2025-01-01-preview" in _captured["url"],
      _captured["url"])
check("api-key header", _captured["headers"].get("api-key") == "test-key-123")

# Message konvertatsiyasi
msgs = _captured["body"]["messages"]
check("birinchi xabar system", msgs[0]["role"] == "system", msgs[0])
check("system matn target so'z bilan", "brave" in msgs[0]["content"])
check("'model' -> 'assistant' ga o'girildi",
      msgs[2]["role"] == "assistant", msgs[2])
check("user xabari matni to'g'ri", msgs[1]["content"] == "I is brave", msgs[1])

# Structured output so'rovi
rf = _captured["body"]["response_format"]
check("response_format json_schema", rf["type"] == "json_schema", rf)
check("strict rejim yoqilgan", rf["json_schema"]["strict"] is True, rf)
check("root additionalProperties False",
      rf["json_schema"]["schema"]["additionalProperties"] is False)

# --- 3. Xato holati (non-retryable) -> AzureOpenAIError ----------------------
print("\n3) Xato holati")


def fake_post_400(url, headers=None, data=None, timeout=None):
    return _Resp(400, {"error": {"message": "bad request"}})


azure_openai.requests.post = fake_post_400
try:
    azure_openai.generate_chat(system, contents)
    check("400 -> AzureOpenAIError", False, "xato ko'tarilmadi")
except azure_openai.AzureOpenAIError:
    check("400 -> AzureOpenAIError", True)

# --- 4. llm dispecheri Azure'ni tanlaydi ------------------------------------
print("\n4) llm.py dispecheri")
check("active_provider = azure (env bor)",
      llm.active_provider() == "azure", llm.active_provider())

# llm.generate_chat xatoni LLMError ga o'raydi
azure_openai.requests.post = fake_post_400
try:
    llm.generate_chat(system, contents)
    check("Azure xatosi -> LLMError", False, "xato yo'q")
except llm.LLMError:
    check("Azure xatosi -> LLMError", True)

# LLM_PROVIDER=gemini bo'lsa Gemini tanlanadi
os.environ["LLM_PROVIDER"] = "gemini"
check("LLM_PROVIDER=gemini -> gemini", llm.active_provider() == "gemini")
del os.environ["LLM_PROVIDER"]

# --- Yakun ------------------------------------------------------------------
print("\n" + "=" * 60)
if FAIL:
    print(f"XATOLAR ({len(FAIL)}):")
    for f in FAIL:
        print("  - " + f)
    sys.exit(1)
print("AZURE OPENAI TEKSHIRUVLARI O'TDI")
