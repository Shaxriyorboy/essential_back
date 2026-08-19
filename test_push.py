"""Aqlli push eslatmalari (device_routes) — FCM MOCK qilinadi.

Ishga tushirish:  ./venv/bin/python test_push.py
"""
import os
import sys
from datetime import date, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".test_tmp")
os.makedirs(SCRATCH, exist_ok=True)
DB_PATH = os.path.join(SCRATCH, "push_test.db")
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH
os.environ["JWT_SECRET"] = "test-secret"
os.environ["CRON_SECRET"] = "cron-secret-123"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402
import device_routes  # noqa: E402
from database import SessionLocal  # noqa: E402
from models import Device, User, UserWord, Word, Unit, Book  # noqa: E402

client = TestClient(main.app)
TODAY = date.today()


def d(n=0):
    return (TODAY + timedelta(days=n)).isoformat()


FAIL = []


def check(label, cond, detail=""):
    print(("  OK   " if cond else "  XATO ") + label
          + ("" if cond else f"  -> {detail}"))
    if not cond:
        FAIL.append(label)


def mk_user(**kw):
    s = SessionLocal()
    u = User(**kw)
    s.add(u); s.commit(); s.refresh(u)
    return u


# --- 0. Fixtura'lar (avval HAMMA yozuv, keyin o'qish — sqlite lock bo'lmasin)
w_setup = SessionLocal()
book = Book(name="Book 1"); w_setup.add(book); w_setup.flush()
unit = Unit(name="U1", book_id=book.id); w_setup.add(unit); w_setup.flush()
w = Word(word_en="apple", word_uz="olma", unit_id=unit.id)
w_setup.add(w); w_setup.commit()
WORD_ID = w.id

u_active = mk_user(email="a@t.com", google_sub="a", last_active_date=d(0))
u_streak = mk_user(email="s@t.com", google_sub="s", current_streak=12,
                   last_active_date=d(-1), streak_freezes=0)
u_frozen = mk_user(email="f@t.com", google_sub="f", current_streak=5,
                   last_active_date=d(-1), streak_freezes=2)
u_due = mk_user(email="due@t.com", google_sub="due", current_streak=0,
                last_active_date=d(-3))
u_new = mk_user(email="new@t.com", google_sub="new", current_streak=0,
                last_active_date=None)

uw_setup = SessionLocal()
uw_setup.add(UserWord(user_id=u_due.id, word_id=WORD_ID, stage=1, due_date=d(0)))
uw_setup.commit()

# --- 1. _build_reminder mantiqi -------------------------------------------
print("1) _build_reminder — holatga qarab matn")
db = SessionLocal()

# 1a) Bugun faol -> None
check("bugun faol -> None",
      device_routes._build_reminder(db, u_active, d(0)) is None)

# 1b) Streak bor, muzlatgich yo'q -> "uziladi"
r = device_routes._build_reminder(db, u_streak, d(0))
check("streak -> streak_reminder", r is not None and r[2] == "streak_reminder", r)
check("12 sarlavhada", "12" in r[0], r[0])
check("muzlatgich yo'q -> 'uziladi'", "uziladi" in r[1], r[1])

# 1c) Streak bor, muzlatgich bor -> yumshoqroq
r = device_routes._build_reminder(db, u_frozen, d(0))
check("muzlatgich bor -> 'muzlatgich' matni", "muzlatgich" in r[1], r[1])

# 1d) Streak yo'q, lekin takrorlash muddati kelgan
r = device_routes._build_reminder(db, u_due, d(0))
check("takrorlash -> review_due", r[2] == "review_due", r)
check("son sarlavhada (1)", "1" in r[0], r[0])

# 1e) Streak yo'q, ish yo'q -> learn_new
r = device_routes._build_reminder(db, u_new, d(0))
check("yangi user -> learn_new", r[2] == "learn_new", r)
db.close()

# --- 2. Endpoint: cron secret himoyasi ------------------------------------
print("\n2) Endpoint xavfsizligi")
r401 = client.post("/devices/send-reminders",
                   headers={"X-Cron-Secret": "wrong"})
check("noto'g'ri secret -> 401", r401.status_code == 401, r401.status_code)

# --- 3. Endpoint: push MOCK bilan yuborish --------------------------------
print("\n3) Yuborish oqimi (FCM mock)")
sent_log = []


def fake_send(token, title, body, data=None):
    sent_log.append({"token": token, "title": title, "type": (data or {}).get("type")})
    # "dead-token" -> unregistered (bazadan o'chirilishi kerak)
    if token == "dead-token":
        return (False, True)
    return (True, False)


device_routes.push.is_configured = lambda: True
device_routes.push.send_to_token = fake_send

# Qurilmalar: streak user (yuboriladi), faol user (skip), o'lik token (prune)
sdb = SessionLocal()
sdb.add(Device(token="live-token", user_id=u_streak.id,
               platform="android", timezone="Asia/Tashkent"))
sdb.add(Device(token="active-token", user_id=u_active.id,
               platform="android", timezone="Asia/Tashkent"))
sdb.add(Device(token="dead-token", user_id=u_due.id,
               platform="android", timezone="Asia/Tashkent"))
sdb.commit()

# force=True — soat tekshiruvini o'tkazib yuboradi
resp = client.post("/devices/send-reminders?force=true",
                   headers={"X-Cron-Secret": "cron-secret-123"}).json()["data"]
types = {s["type"] for s in sent_log}
check("streak user'ga yuborildi", any(s["token"] == "live-token" for s in sent_log))
check("streak_reminder turi", "streak_reminder" in types, types)
check("faol user'ga YUBORILMADI",
      all(s["token"] != "active-token" for s in sent_log))
check("o'lik token prune qwindow (pruned>=1)", resp["pruned"] >= 1, resp)

# O'lik token bazadan o'chdimi
chk = SessionLocal().query(Device).filter(Device.token == "dead-token").first()
check("o'lik token bazadan o'chirildi", chk is None)

# --- Yakun -----------------------------------------------------------------
print("\n" + "=" * 60)
if FAIL:
    print(f"XATOLAR ({len(FAIL)}):")
    for f in FAIL:
        print("  - " + f)
    sys.exit(1)
print("PUSH TEKSHIRUVLARI O'TDI")
