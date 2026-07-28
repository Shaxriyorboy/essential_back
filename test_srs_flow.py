"""SRS oqimini uchdan-uchgacha tekshirish (alohida sqlite bazasida).

Model: bir kunlik sessiya = BITTA UNIT, bosqichma-bosqich (etap).
    Recognise -> Listen -> Produce -> In context -> Fluent (eshit va takrorla)
Har etapda unitning BARCHA so'zlari qatnashadi.

Ishga tushirish:  ./venv/bin/python test_srs_flow.py
"""
import json
import os
import sys
from datetime import date, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".test_tmp")
os.makedirs(SCRATCH, exist_ok=True)
DB_PATH = os.path.join(SCRATCH, "srs_test.db")
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402
import srs  # noqa: E402
from database import SessionLocal  # noqa: E402
from models import Book, Unit, Word, User, UnitCompletion, UserWord  # noqa: E402
from auth import create_access_token  # noqa: E402

EXPORT = os.environ.get(
    "SRS_TEST_EXPORT",
    "/Users/shaxriyortursunaliyev/StudioProjects/essential/"
    "essential_export_2026-06-05.json",
)

# --- Ma'lumot bilan to'ldirish ---------------------------------------------
db = SessionLocal()
data = json.load(open(EXPORT))
n_units = n_words = 0
for b in data["books"][:1]:
    book = Book(name=b.get("name") or "Book 1")
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


def session(H, day, **kw):
    p = {"local_date": day}
    p.update(kw)
    return client.get("/reviews/session", params=p, headers=H).json()["data"]


def answer_for(item, stage, correct=True):
    ex = srs.exercise_for_stage(stage)
    return {"word_id": item["word_id"], "exercise": ex,
            "answer": item["word_en"] if correct else "zzzqqq"}


def run_etap(H, day, words, stage):
    """Bitta etapni oxirigacha o'ynaydi: shu darajadagi hamma so'z."""
    items = [w for w in words if w["stage"] == stage]
    answers = [answer_for(w, stage) for w in items]
    r = client.post("/reviews/submit",
                    json={"local_date": day, "answers": answers},
                    headers=H).json()["data"]
    return items, r


# --- 1. Sessiya = bitta unit -----------------------------------------------
print("1) Sessiya bitta unitdan iborat")
uid, H = new_user("a@t.com")
s = session(H, d())
check("unit qaytdi", s["unit"] is not None, s.get("unit"))
check("unitning HAMMA so'zi keldi", len(s["words"]) == 20, len(s["words"]))
check("hammasi 0-darajada", all(w["stage"] == 0 for w in s["words"]))
check("mcq variantlari bor", all(len(w["options"]) == 4 for w in s["words"]))
# Bosqichga xos ma'lumot BOSHIDANOQ kelishi kerak — etaplarni client quradi
gaps0 = [w for w in s["words"] if w.get("gap_sentence")]
check(f"0-darajadayoq gap_sentence keldi ({len(gaps0)}/20)", len(gaps0) >= 18,
      len(gaps0))
check("gap_answer ham keldi",
      all(w.get("gap_answer") for w in s["words"] if w.get("gap_sentence")))
check("takrorlash bo'sh (birinchi kun)", s["review_items"] == [])
check("max_stage = 4", s["max_stage"] == 4)

# --- 2. Etap tugagach hamma so'z bir daraja ko'tariladi ---------------------
print("\n2) Recognise etapi -> hamma so'z Recall darajasiga")
items, r = run_etap(H, d(), s["words"], 0)
check("20 ta javob qabul qilindi", r["total"] == 20, r["total"])
check("20/20 to'g'ri", r["correct"] == 20, r["correct"])
check("hammasi darajani ko'tardi", len(r["stage_ups"]) == 20, len(r["stage_ups"]))

s2 = session(H, d())
check("1-bosqich mashqi eshitib yozish",
      srs.exercise_for_stage(1) == "listen", srs.exercise_for_stage(1))
check("eski self-rated tur baholanadi (offline navbat uchun)",
      srs.LEGACY_SELF_RATED == "recall_meaning")
check("endi hammasi 1-darajada (Recall)",
      all(w["stage"] == 1 for w in s2["words"]),
      sorted({w["stage"] for w in s2["words"]}))

# --- 3. Hamma etap bitta kunda ---------------------------------------------
print("\n3) Listen, Produce, In context etaplari — o'sha kuni")
run_etap(H, d(), s2["words"], 1)
s3 = session(H, d())
check("hammasi 2-darajada (Produce)",
      all(w["stage"] == 2 for w in s3["words"]),
      sorted({w["stage"] for w in s3["words"]}))

run_etap(H, d(), s3["words"], 2)
s3b = session(H, d())
check("hammasi 3-darajada (In context)",
      all(w["stage"] == 3 for w in s3b["words"]),
      sorted({w["stage"] for w in s3b["words"]}))
gaps = [w for w in s3b["words"] if w.get("gap_sentence")]
check(f"gap_sentence tuzildi ({len(gaps)}/20)", len(gaps) >= 18, len(gaps))
check("katak gapda bor", all("_____" in w["gap_sentence"] for w in gaps))

run_etap(H, d(), s3b["words"], 3)
s3c = session(H, d())
check("hammasi 4-darajada (Fluent)",
      all(w["stage"] == 4 for w in s3c["words"]),
      sorted({w["stage"] for w in s3c["words"]}))
check("4-bosqich mashqi: eshit va takrorla",
      srs.exercise_for_stage(4) == "speak", srs.exercise_for_stage(4))

items, r = run_etap(H, d(), s3c["words"], 4)
check("Fluent etapi bajarildi", r["total"] == 20, r["total"])
check("kunlik maqsad bajarildi", r["goal_met"] is True, r)
check("streak 1 ga oshdi", r["streak"]["current_streak"] == 1, r["streak"])

dbx = SessionLocal()
rows = dbx.query(UserWord).filter_by(user_id=uid).all()
check("hamma so'z MAX darajada", all(x.stage == 4 for x in rows),
      sorted({x.stage for x in rows}))
check("Produce'ga yetgach kun oralig'i boshlandi",
      all(x.due_date > d() for x in rows),
      sorted({x.due_date for x in rows})[:3])

# --- 3c. BOSQICH HISOBI har etapdan keyin ------------------------------------
print("\n3c) Bosqich hisobi har etapdan keyin to'g'ri bo'lsin")
uidp, Hp = new_user("progress@t.com")
DAYP = d(60)
expected = [1, 2, 3, 4, 5]
for stage in range(5):
    sp = session(Hp, DAYP)
    run_etap(Hp, DAYP, sp["words"], stage)
    stp = client.get("/reviews/stats", params={"local_date": DAYP},
                     headers=Hp).json()["data"]
    got = f'{stp["today_done"]}/{stp["today_goal"]}'
    want = f'{expected[stage]}/5'
    check(f"{stage}-etapdan keyin {want}", got == want, got)

# --- 3d. "Ish qolmadi" != "hamma bosqich bajarildi" ------------------------
print("\n3d) Muddati surilgan, lekin bosqichlari tugamagan unit")
uidl, Hl = new_user("legacy@t.com")
DAYL = d(70)
sl = session(Hl, DAYL)
# 3 ta etapni bajaramiz -> so'zlar 3-darajada
for stage in range(3):
    sx = session(Hl, DAYL)
    run_etap(Hl, DAYL, sx["words"], stage)
# Muddatni ERTAGA suramiz (eski model qoldig'iga taqlid) — endi unitda
# "bugungi ish" qolmaydi, lekin 4 va 5-bosqich bajarilmagan
dbl = SessionLocal()
for uw in dbl.query(UserWord).filter_by(user_id=uidl).all():
    uw.due_date = d(71)
dbl.commit()

stl = client.get("/reviews/stats", params={"local_date": DAYL},
                 headers=Hl).json()["data"]
check("ish qolmasa ham hisob 5/5 BO'LMAYDI",
      stl["today_done"] == 3 and stl["today_goal"] == 5,
      f'{stl["today_done"]}/{stl["today_goal"]}')
check("unit_done_today bayrog'i baribir to'g'ri",
      stl["unit_done_today"] is True, stl.get("unit_done_today"))

# --- 3e. XATO QILIB QAYTA TO'G'RILAGAN SO'Z ham darajani ko'taradi ---------
print("\n3e) Xato qilib keyin to'g'rilagan so'z ham ko'tarilishi kerak")
uidr, Hr = new_user("retry@t.com")
DAYR = d(80)
sr = session(Hr, DAYR)
words_r = sr["words"]

# Etapni xuddi client kabi o'ynaymiz: 6 tasiga avval XATO, keyin TO'G'RI
wrong_ids = [w["word_id"] for w in words_r[:6]]
ans = []
for w in words_r:
    if w["word_id"] in wrong_ids:
        ans.append({"word_id": w["word_id"], "exercise": "mcq",
                    "answer": "zzzqqq"})           # xato
    else:
        ans.append({"word_id": w["word_id"], "exercise": "mcq",
                    "answer": w["word_en"]})
# xato qilinganlar navbat oxirida QAYTA chiqadi va to'g'ri javob beriladi
for w in words_r:
    if w["word_id"] in wrong_ids:
        ans.append({"word_id": w["word_id"], "exercise": "mcq",
                    "answer": w["word_en"]})

r = client.post("/reviews/submit",
                json={"local_date": DAYR, "answers": ans},
                headers=Hr).json()["data"]
check("hamma 20 ta so'z darajani ko'tardi",
      len(r["stage_ups"]) == 20, len(r["stage_ups"]))

s2r = session(Hr, DAYR)
stages_r = sorted({w["stage"] for w in s2r["words"]})
check("keyingi sessiyada hammasi 1-darajada (hech biri qolib ketmadi)",
      stages_r == [1], stages_r)

dbr = SessionLocal()
lapsed = dbr.query(UserWord).filter(
    UserWord.user_id == uidr, UserWord.lapses > 0).count()
check("xatolar `lapses` da qayd etildi", lapsed == 6, lapsed)

# --- 4. KUNIGA BITTA UNIT ---------------------------------------------------
print("\n4) Kuniga bitta unit — yangisi ertaga ochiladi")
s4today = session(H, d())
check("BUGUN yangi unit berilmaydi", s4today["unit"] is None, s4today.get("unit"))
check("unit_done_today bayrog'i", s4today["unit_done_today"] is True, s4today)

s4 = session(H, d(1))
check("ERTAGA yangi unit ochiladi", s4["unit"] is not None
      and s4["unit"]["id"] != s["unit"]["id"],
      s4.get("unit"))
check("yangi unitda 20 ta so'z", len(s4["words"]) == 20, len(s4["words"]))
check("hammasi 0-darajadan boshlanadi",
      all(w["stage"] == 0 for w in s4["words"]))

# --- 5. Xato javob darajani ko'tarmaydi ------------------------------------
print("\n5) Xato javob darajani ko'tarmaydi")
uid2, H2 = new_user("b@t.com")
sb = session(H2, d())
one = sb["words"][0]
r = client.post("/reviews/submit", json={"local_date": d(), "answers": [
    answer_for(one, 0, correct=False)]}, headers=H2).json()["data"]
res = r["results"][0]
check("xato deb baholandi", res["correct"] is False, res)
check("daraja 0 da qoldi", res["stage"] == 0, res)
check("to'g'ri javob qaytarildi", "expected" in res, res)
check("o'sha kuni qayta chiqadi", res["next_due"] == d(), res)

# --- 6. Muddati kelgan so'zlar alohida "Takrorlash" etapida ------------------
print("\n6) Oldingi unitlardan takrorlash alohida keladi")
# Joriy unit 2-unitga o'tishi uchun u yerda ham ish qilamiz, so'ng 1-unit
# so'zlarining muddatini bugunga qo'yamiz — o'shalar "Takrorlash" bo'lib keladi.
first_unit_word_ids = [w["word_id"] for w in s["words"]]
run_etap(H, d(1), s4["words"], 0)
dby = SessionLocal()
for uw in dby.query(UserWord).filter(
        UserWord.user_id == uid,
        UserWord.word_id.in_(first_unit_word_ids)).all():
    uw.due_date = d(1)
dby.commit()
s6 = session(H, d(1))
check("review_items to'ldi", len(s6["review_items"]) > 0, len(s6["review_items"]))
cur_ids = {w["word_id"] for w in s6["words"]}
check("takrorlash so'zlari joriy unitdan EMAS",
      all(i["word_id"] not in cur_ids for i in s6["review_items"]))

# --- 7. Imlo toleransi -----------------------------------------------------
print("\n7) Imlo toleransi (yozish mashqi)")
long_w = next(w for w in s6["words"] if len(w["word_en"]) > 5)
dbz = SessionLocal()
uw = dbz.query(UserWord).filter_by(
    user_id=uid, word_id=long_w["word_id"]).first()
if uw is None:
    uw = UserWord(user_id=uid, word_id=long_w["word_id"], stage=4, stage_reps=0,
                  step=1, ease=250, interval_days=1, due_date=d(1), reps=1)
    dbz.add(uw)
else:
    uw.stage = 4
    uw.due_date = d(1)
dbz.commit()
w = long_w["word_en"]
typo = w[:-2] + w[-1] + w[-2]
r = client.post("/reviews/submit", json={"local_date": d(1), "answers": [
    {"word_id": long_w["word_id"], "exercise": "type_production",
     "answer": typo}]}, headers=H).json()["data"]
check(f"transpozitsiya kechiriladi ({w!r} <- {typo!r})",
      r["results"][0]["correct"] is True, r["results"][0])
r = client.post("/reviews/submit", json={"local_date": d(2), "answers": [
    {"word_id": long_w["word_id"], "exercise": "type_production",
     "answer": "qwertyzz"}]}, headers=H).json()["data"]
check("butunlay boshqa javob rad etiladi",
      r["results"][0]["correct"] is False, r["results"][0])

# --- 8. STREAK DEVORI ------------------------------------------------------
print("\n8) Streak devori — hamma unit tugagan user ham streak oladi")
uid3, H3 = new_user("c@t.com")
db3 = SessionLocal()
for unit in db3.query(Unit).all():
    db3.add(UnitCompletion(user_id=uid3, unit_id=unit.id, score=100))
db3.commit()

unit_any = db3.query(Unit).first()
qz = client.get(f"/quiz/unit/{unit_any.id}?count=5").json()["data"]
qa = [{"word_id": q["id"], "answer": q["correct"]} for q in qz]
r = client.post("/quiz/submit", json={"source": "quiz", "local_date": d(20),
                                      "unit_id": unit_any.id, "answers": qa},
                headers=H3).json()["data"]
check("eski quiz yo'li streak bermaydi (devor mavjud edi)",
      r["streak"]["increased"] is False, r["streak"])

s8 = session(H3, d(20))
_, r = run_etap(H3, d(20), s8["words"], 0)
check("YANGI yo'l: sessiya streak beradi",
      r["streak"]["increased"] is True and r["streak"]["current_streak"] == 1,
      r["streak"])

# --- 9. Statistika ---------------------------------------------------------
print("\n9) Statistika")
st = client.get("/reviews/stats", params={"local_date": d(20)},
                headers=H3).json()["data"]
check("today_goal unit hajmiga bog'landi", st["unit_size"] == 20,
      st.get("unit_size"))
check("unit nomi qaytdi", st.get("unit_name") is not None, st.get("unit_name"))
check("bosqich hisobi: 1/5 (faqat Recognise)",
      st["today_done"] == 1 and st["today_goal"] == 5,
      f'{st["today_done"]}/{st["today_goal"]}')
check("so'z hisobi alohida maydonda", st["words_done_today"] == 20,
      st.get("words_done_today"))
check("aktiv so'z 0 (hali suhbat bo'lmagan)", st["active_words"] == 0)

# --- 9b. FLUENT: suhbatda erkin ishlatish -----------------------------------
print("\n9b) Fluent — suhbatda erkin ishlatilgan so'z 4-darajaga chiqadi")
from speaking_routes import _record_active_uses
dbf = SessionLocal()
fl_words = dbf.query(Word).filter(Word.id.in_(
    [x.word_id for x in dbf.query(UserWord).filter_by(user_id=uid).limit(3).all()]
)).all()
# Bu so'zlar 3-darajada (barcha yozma bosqichdan o'tgan)
for uw in dbf.query(UserWord).filter(
        UserWord.user_id == uid,
        UserWord.word_id.in_([w.id for w in fl_words])).all():
    uw.stage = 3
    uw.active_uses = 0
dbf.commit()

names = [w.word_en for w in fl_words]
p1 = _record_active_uses(SessionLocal(), uid, names, fl_words)
check("suhbat hisobi yozildi", len(p1) == len(fl_words), p1)

dbg = SessionLocal()
check("DARAJA o'zgarmadi (Fluent etap orqali olinadi)",
      all((dbg.query(UserWord).filter_by(user_id=uid, word_id=w.id)
           .first().stage) == 3 for w in fl_words))
check("active_uses oshdi",
      all((dbg.query(UserWord).filter_by(user_id=uid, word_id=w.id)
           .first().active_uses) == 1 for w in fl_words))

# SRS'ga kirmagan so'z hisobga olinmaydi
unseen = dbg.query(Word).filter(~Word.id.in_(
    [x.word_id for x in dbg.query(UserWord.word_id).filter_by(user_id=uid).all()]
)).first()
if unseen is not None:
    r1 = _record_active_uses(SessionLocal(), uid, [unseen.word_en], [unseen])
    check("SRS'ga kirmagan so'z hisobga olinmaydi", r1 == [], r1)

# --- 10. Migratsiya --------------------------------------------------------
print("\n10) Migratsiya")
from migrate_srs import migrate  # noqa: E402
res = migrate(SessionLocal(), dry_run=True)
check("dry-run yozuv qo'shmaydi", "would_insert" in res, res)
migrate(SessionLocal())
check("idempotent (ikkinchi marta 0)",
      migrate(SessionLocal())["inserted"] == 0)

# --- Yakun -----------------------------------------------------------------
print("\n" + "=" * 60)
if FAIL:
    print(f"XATOLAR ({len(FAIL)}):")
    for f in FAIL:
        print("  - " + f)
    sys.exit(1)
print("HAMMA TEKSHIRUV O'TDI")
