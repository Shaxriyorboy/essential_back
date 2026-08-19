"""Bosh ekran ("Bugun" / TodayPage) holatlarini uchdan-uchgacha tekshirish.

Bu test FAQAT bosh ekranga tegishli: `/reviews/stats` va `/reviews/session`
javoblari asosida TodayPage qaysi holatni ko'rsatishini tekshiradi.

Frontend mantig'i (ReviewStats getter'lari) shu yerda AYNAN takrorlanadi —
maqsad backend javobi bilan UI qarori mos kelishini isbotlash.

Ishga tushirish:  ./venv/bin/python test_home_page.py
"""
import json
import os
import sys
from datetime import date, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".test_tmp")
os.makedirs(SCRATCH, exist_ok=True)
DB_PATH = os.path.join(SCRATCH, "home_test.db")
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402
import srs  # noqa: E402
from database import SessionLocal  # noqa: E402
from models import Book, Unit, Word, User, UserWord  # noqa: E402
from auth import create_access_token  # noqa: E402

EXPORT = os.environ.get(
    "SRS_TEST_EXPORT",
    "/Users/shaxriyortursunaliyev/StudioProjects/essential/"
    "essential_export_2026-06-05.json",
)

# --- Ma'lumot bilan to'ldirish (2 kitob, har birida bir necha unit) --------
db = SessionLocal()
data = json.load(open(EXPORT))
n_units = n_words = 0
for b in data["books"][:2]:
    book = Book(name=b.get("name") or "Book")
    db.add(book); db.flush()
    for u in b.get("units", [])[:4]:
        unit = Unit(name=u.get("name"), history=u.get("history"), book_id=book.id)
        db.add(unit); db.flush(); n_units += 1
        for w in u.get("words", []):
            db.add(Word(
                word_en=w["word_en"], word_uz=w["word_uz"],
                definition=w.get("definition"), phonetic=w.get("phonetic"),
                example=w.get("example"), word_classes=w.get("word_classes"),
                unit_id=unit.id,
            ))
            n_words += 1
db.commit()
print(f"Baza: {n_units} unit, {n_words} so'z\n")

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


def new_user(email):
    s = SessionLocal()
    u = User(email=email, name=email, google_sub=email)
    s.add(u); s.commit(); s.refresh(u)
    return u.id, {"Authorization": "Bearer " + create_access_token(u.id)}


def stats(H, day):
    return client.get("/reviews/stats", params={"local_date": day},
                      headers=H).json()["data"]


def session(H, day, **kw):
    p = {"local_date": day}; p.update(kw)
    return client.get("/reviews/session", params=p, headers=H).json()["data"]


def run_etap(H, day, words, stage):
    items = [w for w in words if w["stage"] == stage]
    answers = [{"word_id": w["word_id"],
                "exercise": srs.exercise_for_stage(stage),
                "answer": w["word_en"]} for w in items]
    return client.post("/reviews/submit",
                       json={"local_date": day, "answers": answers},
                       headers=H).json()["data"]


def finish_unit(H, day, first_session):
    """Bir unitni to'liq (5 bosqich) o'ynab tugatadi."""
    s = first_session
    for stage in range(5):
        s = session(H, day)
        run_etap(H, day, s["words"], stage)


# --- Frontend getter'larining AYNAN nusxasi (review_stats.dart) ------------
# UI aynan shu qiymatlarga qarab qaror qiladi; shuni bu yerda tekshiramiz.

class Stats:
    def __init__(self, j):
        self.today_done = j["today_done"]
        self.today_goal = j["today_goal"]
        self.due_today = j["due_today"]
        self.due_tomorrow = j["due_tomorrow"]
        self.started_words = j["started_words"]
        self.total_words = j["total_words"]
        self.active_words = j["active_words"]
        self.unit_name = j.get("unit_name")
        self.unit_done_today = j["unit_done_today"]
        self.current_streak = j["current_streak"]

    @property
    def has_due_reviews(self):
        # ReviewStats.hasDueReviews
        return self.due_today > 0

    @property
    def has_more_work(self):
        # ReviewStats.hasMoreWork (E holati tuzatilgandan keyin)
        return self.has_due_reviews or (
            not self.unit_done_today and self.started_words < self.total_words)

    @property
    def progress(self):
        # ReviewStats.progress
        if self.today_goal <= 0:
            return 1.0 if self.today_done > 0 else 0.0
        v = self.today_done / self.today_goal
        return 1.0 if v > 1 else v

    def home_state(self):
        """TodayPage `_DailyGoalCard` qaysi shoxni ko'rsatadi."""
        if self.unit_done_today:
            # Unit tugadi, lekin muddati kelgan takrorlash bo'lsa — tugma bor
            return ("UNIT_DONE_REVIEWS" if self.has_due_reviews
                    else "UNIT_DONE_TOMORROW")
        if not self.has_more_work:
            return "ALL_DONE"               # "Hammasi tugadi"
        return "IN_PROGRESS"                # halqa + Boshlash/Davom tugmasi

    def shows_start_button(self):
        return self.has_more_work


# ==========================================================================
print("A) Yangi foydalanuvchi — birinchi ochilish")
uid, H = new_user("home_new@t.com")
st = Stats(stats(H, d()))
check("holat: IN_PROGRESS", st.home_state() == "IN_PROGRESS", st.home_state())
check("Boshlash tugmasi ko'rinadi", st.shows_start_button() is True)
check("unit nomi bor", bool(st.unit_name), st.unit_name)
check("halqa 0/5", st.today_done == 0 and st.today_goal == 5,
      f"{st.today_done}/{st.today_goal}")
check("progress = 0.0", st.progress == 0.0, st.progress)
check("streak yo'q", st.current_streak == 0)
check("session bo'sh EMAS", not (len(session(H, d())["words"]) == 0))

print("\nB) Bitta etap bajarilgach — Davom holati")
s = session(H, d())
run_etap(H, d(), s["words"], 0)   # Recognise
st = Stats(stats(H, d()))
check("holat: IN_PROGRESS", st.home_state() == "IN_PROGRESS", st.home_state())
check("halqa 1/5", st.today_done == 1 and st.today_goal == 5,
      f"{st.today_done}/{st.today_goal}")
check("tugma hamon bor (davom)", st.shows_start_button() is True)

print("\nC) Unit to'liq tugatildi (bugun) — ertaga holati")
finish_unit(H, d(), s)
st = Stats(stats(H, d()))
check("holat: UNIT_DONE_TOMORROW",
      st.home_state() == "UNIT_DONE_TOMORROW", st.home_state())
check("Boshlash tugmasi YO'Q", st.shows_start_button() is False)
check("unit_done_today = True", st.unit_done_today is True)
check("streak 1 ga oshdi", st.current_streak == 1, st.current_streak)

print("\nD) Ertaga — yangi unit ochiladi")
st2 = Stats(stats(H, d(1)))
check("holat: IN_PROGRESS", st2.home_state() == "IN_PROGRESS", st2.home_state())
check("Boshlash tugmasi bor", st2.shows_start_button() is True)
check("yangi unit nomi (avvalgidan farqli)",
      st2.unit_name != st.unit_name, (st.unit_name, st2.unit_name))
check("halqa 0/5 ga qaytdi", st2.today_done == 0, st2.today_done)

# ==========================================================================
# E) MUHIM chekka holat: bugungi unit tugadi, LEKIN eski takrorlashlar
#    muddati bugunga kelgan. Session bu so'zlarni beradi (review_items),
#    ammo stats `unit_done_today=True` deb tugmani yashiradi.
#    Bu — session bilan stats o'rtasidagi NOMUVOFIQLIK.
print("\nE) Chekka holat: unit tugadi, eski takrorlash muddati BUGUN kelgan")
uidx, Hx = new_user("home_review@t.com")
# 1-unitni to'liq tugatamiz (day 0)
s0 = session(Hx, d(0))
first_unit_ids = [w["word_id"] for w in s0["words"]]
finish_unit(Hx, d(0), s0)

# 2-unitni (ertaga) to'liq tugatamiz (day 1)
s1 = session(Hx, d(1))
finish_unit(Hx, d(1), s1)

# Endi 1-unit so'zlarining muddatini "bugun" (day 1) ga suramiz —
# ya'ni ular takrorlashga tayyor. 2-unit day 1 da tugatilgan.
dbx = SessionLocal()
for uw in dbx.query(UserWord).filter(
        UserWord.user_id == uidx,
        UserWord.word_id.in_(first_unit_ids)).all():
    uw.due_date = d(1)
dbx.commit()

sess = session(Hx, d(1))
st = Stats(stats(Hx, d(1)))
n_reviews = len(sess["review_items"])
print(f"     (session review_items = {n_reviews}, "
      f"stats.due_today = {st.due_today}, "
      f"unit_done_today = {st.unit_done_today})")

check("session HAQIQATDA takrorlash beradi (review_items>0)",
      n_reviews > 0, n_reviews)
check("stats.due_today ham >0", st.due_today > 0, st.due_today)

# TUZATILDI: endi bosh ekran takrorlashni ochib beradi.
check("holat: UNIT_DONE_REVIEWS (takrorlash mavjud)",
      st.home_state() == "UNIT_DONE_REVIEWS", st.home_state())
check("Takrorlash tugmasi ENDI KO'RINADI",
      st.shows_start_button() is True, st.shows_start_button())
check("hasMoreWork = True (muddati kelgan ish bor)",
      st.has_more_work is True)

# ==========================================================================
# F) Butun korpus tugagan foydalanuvchi (yangi so'z ham, takrorlash ham yo'q)
print("\nF) Hamma so'z ko'rilgan, bugun muddati kelgan yo'q — Hammasi tugadi")
uidz, Hz = new_user("home_alldone@t.com")
dbz = SessionLocal()
# Barcha so'zni MAX darajada, muddati kelajakda deб belgilaymiz
all_words = dbz.query(Word).all()
for w in all_words:
    dbz.add(UserWord(user_id=uidz, word_id=w.id, stage=4, stage_reps=0,
                     step=3, ease=250, interval_days=16, due_date=d(30),
                     reps=5, lapses=0, last_review_date=d(-5),
                     first_seen_at=None))
dbz.commit()
st = Stats(stats(Hz, d()))
print(f"     (started={st.started_words}, total={st.total_words}, "
      f"due_today={st.due_today}, unit_done_today={st.unit_done_today})")
check("holat: ALL_DONE yoki UNIT_DONE (tugma yo'q)",
      st.shows_start_button() is False, st.home_state())

# --- Yakun -----------------------------------------------------------------
print("\n" + "=" * 60)
if FAIL:
    print(f"XATOLAR ({len(FAIL)}):")
    for f in FAIL:
        print("  - " + f)
    sys.exit(1)
print("BOSH EKRAN TEKSHIRUVLARI O'TDI")
