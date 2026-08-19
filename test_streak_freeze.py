"""Streak muzlatgichi (streak freeze) + rewarded ad oqimini tekshiradi.

Ishga tushirish:  ./venv/bin/python test_streak_freeze.py
"""
import os
import sys
from datetime import date, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".test_tmp")
os.makedirs(SCRATCH, exist_ok=True)
DB_PATH = os.path.join(SCRATCH, "freeze_test.db")
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402
import streak  # noqa: E402
from database import SessionLocal  # noqa: E402
from models import User, StreakFreezeLog  # noqa: E402
from auth import create_access_token  # noqa: E402

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


def new_user(email, **kw):
    s = SessionLocal()
    u = User(email=email, name=email, google_sub=email, **kw)
    s.add(u); s.commit(); s.refresh(u)
    return u.id, {"Authorization": "Bearer " + create_access_token(u.id)}


def reget(uid):
    return SessionLocal().query(User).filter_by(id=uid).first()


def close_in_session(uid, day, score=100):
    """`close_day` ni bitta sessiyada chaqiradi (prod'dagidek: user va db bir
    xil sessiyadan). Turli sessiyani aralashtirish `db.refresh` ni buzadi."""
    s = SessionLocal()
    u = s.query(User).filter_by(id=uid).first()
    return streak.close_day(s, u, day, "review", score)


# --- 1. Reklama ko'rib muzlatgich topish -----------------------------------
print("1) Rewarded ad -> muzlatgich topish + cheklovlar")
uid, H = new_user("earn@t.com")
r = client.post("/streak/earn-freeze", json={"local_date": d()},
                headers=H).json()["data"]
check("birinchi topish ok", r["ok"] is True, r)
check("muzlatgich 1 ta bo'ldi", r["streak_freezes"] == 1, r)
check("max_freezes qaytdi", r["max_freezes"] == streak.MAX_FREEZES_HELD, r)

# Kunlik cheklov: bir kunda ikkinchisiga ruxsat yo'q (EARN_PER_DAY_CAP=1)
r2 = client.post("/streak/earn-freeze", json={"local_date": d()},
                 headers=H).json()["data"]
check("kunlik cheklov ishladi (ikkinchisi rad)", r2["ok"] is False, r2)
check("sabab = daily_cap", r2["reason"] == "daily_cap", r2)
check("muzlatgich hamon 1", r2["streak_freezes"] == 1, r2)

# --- 2. Maksimum ushlash cheklovi ------------------------------------------
print("\n2) MAX_FREEZES_HELD cheklovi")
uid2, H2 = new_user("maxheld@t.com")
# Har xil kunda MAX_FREEZES_HELD marta topamiz
for i in range(streak.MAX_FREEZES_HELD):
    rr = client.post("/streak/earn-freeze", json={"local_date": d(i)},
                     headers=H2).json()["data"]
check(f"{streak.MAX_FREEZES_HELD} ta yig'ildi",
      reget(uid2).streak_freezes == streak.MAX_FREEZES_HELD,
      reget(uid2).streak_freezes)
# Yana bitta — max ga yetgani uchun rad etilishi kerak
rr = client.post("/streak/earn-freeze",
                 json={"local_date": d(streak.MAX_FREEZES_HELD)},
                 headers=H2).json()["data"]
check("max ga yetgach rad etildi", rr["ok"] is False, rr)
check("sabab = max_held", rr["reason"] == "max_held", rr)

# --- 3. close_day: 1 kunlik tanaffusni muzlatgich yopadi --------------------
print("\n3) Muzlatgich 1 kunlik tanaffusni yopadi (streak saqlanadi)")
uid3, H3 = new_user("bridge@t.com", current_streak=10, longest_streak=10,
                    last_active_date=d(0), streak_freezes=1)
# Kecha (d(1)) o'tkazib yuborildi, bugun d(2) — 1 kun tanaffus
s3 = close_in_session(uid3, d(2))
check("streak UZILMADI (10 -> 11)", s3["current_streak"] == 11, s3)
check("muzlatgich ishlatildi (freeze_used)", s3["freeze_used"] is True, s3)
check("muzlatgich 1 -> 0", s3["streak_freezes"] == 0, s3)

# --- 4. Muzlatgich yo'q -> streak uziladi ----------------------------------
print("\n4) Muzlatgich yo'q — tanaffus streakni uzadi")
uid4, H4 = new_user("nofreeze@t.com", current_streak=10, longest_streak=10,
                    last_active_date=d(0), streak_freezes=0)
s4 = close_in_session(uid4, d(2))
check("streak uzildi (1 ga tushdi)", s4["current_streak"] == 1, s4)
check("muzlatgich ishlatilmadi", s4["freeze_used"] is False, s4)

# --- 5. Ketma-ket kun — muzlatgich ISHLATILMAYDI ---------------------------
print("\n5) Ketma-ket faol kun — muzlatgich sarflanmaydi")
uid5, H5 = new_user("consec@t.com", current_streak=5, longest_streak=5,
                    last_active_date=d(0), streak_freezes=2)
s5 = close_in_session(uid5, d(1))
check("streak oddiy oshdi (5 -> 6)", s5["current_streak"] == 6, s5)
check("muzlatgich saqlanib qoldi (2)", s5["streak_freezes"] == 2, s5)
check("freeze_used False", s5["freeze_used"] is False, s5)

# --- 6. Juda katta tanaffus — muzlatgich yetsa ham uziladi ------------------
print("\n6) MAX_FREEZE_BRIDGE_DAYS dan katta tanaffus — uziladi")
uid6, H6 = new_user("biggap@t.com", current_streak=20, longest_streak=20,
                    last_active_date=d(0), streak_freezes=3)
gap = streak.MAX_FREEZE_BRIDGE_DAYS + 2   # ko'prik chegarasidan katta
s6 = close_in_session(uid6, d(gap + 1))
check("katta tanaffusda streak uzildi", s6["current_streak"] == 1, s6)
check("muzlatgich sarflanmadi (3 saqlandi)", s6["streak_freezes"] == 3, s6)

# --- 7. 2 kunlik tanaffus — 2 muzlatgich sarflab yopiladi ------------------
print("\n7) 2 kunlik tanaffus — 2 muzlatgich sarflaydi")
uid7, H7 = new_user("twogap@t.com", current_streak=8, longest_streak=8,
                    last_active_date=d(0), streak_freezes=2)
s7 = close_in_session(uid7, d(3))  # 2 kun tanaffus
check("streak saqlandi (8 -> 9)", s7["current_streak"] == 9, s7)
check("2 muzlatgich sarflandi (2 -> 0)", s7["streak_freezes"] == 0, s7)
check("freeze_used True", s7["freeze_used"] is True, s7)

# --- 8. GET /streak holati -------------------------------------------------
print("\n8) GET /streak holati")
st = client.get("/streak", headers=H).json()["data"]
check("current_streak maydoni bor", "current_streak" in st, st)
check("streak_freezes maydoni bor", "streak_freezes" in st, st)
check("max_freezes maydoni bor", "max_freezes" in st, st)

# --- 9. /reviews/stats ichida streak_freezes -------------------------------
print("\n9) /reviews/stats muzlatgich sonini beradi")
stats = client.get("/reviews/stats", params={"local_date": d()},
                   headers=H).json()["data"]
check("stats.streak_freezes bor", "streak_freezes" in stats, stats)

# --- Yakun -----------------------------------------------------------------
print("\n" + "=" * 60)
if FAIL:
    print(f"XATOLAR ({len(FAIL)}):")
    for f in FAIL:
        print("  - " + f)
    sys.exit(1)
print("MUZLATGICH TEKSHIRUVLARI O'TDI")
