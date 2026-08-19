"""AI Speaking Partner endpoint'larini tekshiradi (Gemini MOCK qilinadi).

Haqiqiy Gemini chaqirilmaydi — `generate_chat` soxta funksiya bilan
almashtiriladi. Shunda test tashqi API'ga, kalitga va internetga bog'liq
bo'lmaydi, lekin endpoint mantig'i (kvota, tarix, active-use, javob
strukturasi) to'liq tekshiriladi.

Ishga tushirish:  ./venv/bin/python test_speaking.py
"""
import json
import os
import sys
from datetime import date

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".test_tmp")
os.makedirs(SCRATCH, exist_ok=True)
DB_PATH = os.path.join(SCRATCH, "speaking_test.db")
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402
import speaking_routes  # noqa: E402
from database import SessionLocal  # noqa: E402
from models import Book, Unit, Word, User  # noqa: E402
from auth import create_access_token  # noqa: E402

EXPORT = os.environ.get(
    "SRS_TEST_EXPORT",
    "/Users/shaxriyortursunaliyev/StudioProjects/essential/"
    "essential_export_2026-06-05.json",
)

# --- Baza ------------------------------------------------------------------
db = SessionLocal()
data = json.load(open(EXPORT))
b = data["books"][0]
book = Book(name=b.get("name") or "Book 1")
db.add(book); db.flush()
u = b["units"][0]
unit = Unit(name=u.get("name"), history=u.get("history"), book_id=book.id)
db.add(unit); db.flush()
for w in u.get("words", []):
    db.add(Word(word_en=w["word_en"], word_uz=w["word_uz"],
                definition=w.get("definition"), phonetic=w.get("phonetic"),
                example=w.get("example"), word_classes=w.get("word_classes"),
                unit_id=unit.id))
db.commit()
UNIT_ID = unit.id
FIRST_WORD = db.query(Word).filter(Word.unit_id == UNIT_ID).order_by(Word.id).first()
print(f"Baza: 1 unit, {db.query(Word).filter(Word.unit_id==UNIT_ID).count()} so'z\n")

client = TestClient(main.app)
TODAY = date.today().isoformat()
FAIL = []


def check(label, cond, detail=""):
    print(("  OK   " if cond else "  XATO ") + label
          + ("" if cond else f"  -> {detail}"))
    if not cond:
        FAIL.append(label)


def new_user(email):
    s = SessionLocal()
    us = User(email=email, name=email, google_sub=email)
    s.add(us); s.commit(); s.refresh(us)
    return us.id, {"Authorization": "Bearer " + create_access_token(us.id)}


# --- Gemini MOCK -----------------------------------------------------------
# Har chaqiruvni sanaymiz + oxirgi argumentlarni saqlaymiz (tekshirish uchun).
_calls = {"n": 0, "system": None, "contents": None, "model": None}


def fake_generate_chat(system_instruction, contents, preferred_model=None):
    _calls["n"] += 1
    _calls["system"] = system_instruction
    _calls["contents"] = contents
    _calls["model"] = preferred_model
    return {
        "reply": "Nice! Tell me more about your day.",
        "corrections": [
            {"original": "I goed", "fixed": "I went", "note": "past tense of 'go'"}
        ],
        "target_words_used_by_user": [FIRST_WORD.word_en],
        "target_words_introduced": [],
    }


speaking_routes.generate_chat = fake_generate_chat  # monkeypatch

uid, H = new_user("speak@t.com")

# --- 1. Kvota (boshlang'ich) -----------------------------------------------
print("1) Boshlang'ich kvota")
q = client.get("/speaking/quota", headers=H).json()["data"]
check("tier = free", q["tier"] == "free", q.get("tier"))
check("kunlik limit = 300s (5 daqiqa)", q["daily_limit_seconds"] == 300, q)
check("used = 0", q["seconds_used"] == 0, q)
check("limit_reached = False", q["limit_reached"] is False, q)

# --- 2. Suhbat aylanasi (chat) ---------------------------------------------
print("\n2) Suhbat aylanasi")
body = {
    "source": "unit", "unit_id": UNIT_ID, "locale": "uz",
    "messages": [{"role": "user", "text": "Hello, I goed to school today"}],
    "elapsed_seconds": 30,
}
r = client.post("/speaking/chat", json=body, headers=H).json()
check("HTTP envelope success", r["success"] is True, r.get("code"))
d = r["data"]
check("Gemini bir marta chaqirildi", _calls["n"] == 1, _calls["n"])
check("reply qaytdi", d["reply"].startswith("Nice!"), d.get("reply"))
check("correction o'tkazildi", len(d["corrections"]) == 1, d.get("corrections"))
check("free tarif modeli flash-lite",
      _calls["model"] == "gemini-2.5-flash-lite", _calls["model"])
check("system prompt target so'zlarni o'z ichiga oladi",
      FIRST_WORD.word_en in _calls["system"], "word yo'q")
check("vaqt 30s ga oshdi", d["seconds_used"] == 30, d.get("seconds_used"))
check("qolgan vaqt 270s", d["seconds_left"] == 270, d.get("seconds_left"))

# --- 3. Tarix saqlandi -----------------------------------------------------
print("\n3) Suhbat tarixi saqlandi")
h = client.get("/speaking/history", params={"source": "unit", "unit_id": UNIT_ID},
               headers=H).json()["data"]
msgs = h["messages"]
check("2 ta xabar saqlandi (user + AI)", len(msgs) == 2, len(msgs))
roles = [m["role"] for m in msgs]
check("rollar to'g'ri tartibda", roles == ["user", "assistant"] or
      roles == ["user", "model"], roles)
check("level qaytdi", bool(h.get("level")), h.get("level"))

# --- 4. Consume (xabarsiz vaqt sarfi) --------------------------------------
print("\n4) Consume — xabar yubormay vaqt qo'shish")
c = client.post("/speaking/consume",
                json={"source": "unit", "unit_id": UNIT_ID, "elapsed_seconds": 60},
                headers=H).json()["data"]
check("vaqt 90s ga yetdi (30+60)", c["seconds_used"] == 90, c.get("seconds_used"))
check("Gemini chaqirilmadi (consume)", _calls["n"] == 1, _calls["n"])

# --- 5. Kunlik vaqt limiti -------------------------------------------------
print("\n5) Kunlik limit tugaganda Gemini CHAQIRILMAYDI")
# Qolgan ~210s ni consume bilan tugatamiz (MAX_TURN_SECONDS=180 ga qisiladi)
client.post("/speaking/consume",
            json={"source": "unit", "unit_id": UNIT_ID, "elapsed_seconds": 180},
            headers=H)
client.post("/speaking/consume",
            json={"source": "unit", "unit_id": UNIT_ID, "elapsed_seconds": 180},
            headers=H)
before = _calls["n"]
r2 = client.post("/speaking/chat", json=body, headers=H).json()
check("limit_reached envelope (code 429)", r2["code"] == 429, r2.get("code"))
check("limit tugagach Gemini CHAQIRILMADI", _calls["n"] == before, _calls["n"])
check("data.limit_reached = True", r2["data"]["limit_reached"] is True, r2["data"])

# --- 6. Xato holatlar ------------------------------------------------------
print("\n6) Xato holatlar")
uid2, H2 = new_user("speak2@t.com")
# 6a) favorites — sevimlilar yo'q
rf = client.post("/speaking/chat",
                 json={"source": "favorites", "locale": "uz",
                       "messages": [{"role": "user", "text": "hi"}],
                       "elapsed_seconds": 5},
                 headers=H2).json()
check("favorites bo'sh bo'lsa 400", rf["code"] == 400, rf.get("code"))
# 6b) unit source, unit_id yo'q
ru = client.post("/speaking/chat",
                 json={"source": "unit", "locale": "uz",
                       "messages": [{"role": "user", "text": "hi"}],
                       "elapsed_seconds": 5},
                 headers=H2)
check("unit_id yo'q bo'lsa 400", ru.status_code == 400, ru.status_code)
# 6c) auth yo'q
rn = client.post("/speaking/chat", json=body)
check("token yo'q bo'lsa 401", rn.status_code == 401, rn.status_code)

# --- 7. Gemini xatosi (502) ------------------------------------------------
print("\n7) Gemini xatosi bo'lganda 502 + vaqt sarflanmaydi")
from gemini import GeminiError


def failing_generate(*a, **k):
    raise GeminiError("high demand")


speaking_routes.generate_chat = failing_generate
uid3, H3 = new_user("speak3@t.com")
rerr = client.post("/speaking/chat", json=body, headers=H3)
check("Gemini xatosida 502", rerr.status_code == 502, rerr.status_code)
q3 = client.get("/speaking/quota", headers=H3).json()["data"]
check("xato bo'lganda vaqt sarflanmadi (used=0)",
      q3["seconds_used"] == 0, q3.get("seconds_used"))

# --- Yakun -----------------------------------------------------------------
print("\n" + "=" * 60)
if FAIL:
    print(f"XATOLAR ({len(FAIL)}):")
    for f in FAIL:
        print("  - " + f)
    sys.exit(1)
print("SPEAKING TEKSHIRUVLARI O'TDI")
