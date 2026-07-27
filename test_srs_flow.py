"""SRS oqimini uchdan-uchgacha tekshirish (alohida sqlite bazasida)."""
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
from database import SessionLocal  # noqa: E402
from models import Book, Unit, Word, User, UnitCompletion  # noqa: E402
from auth import create_access_token  # noqa: E402

EXPORT = os.environ.get("SRS_TEST_EXPORT", "../essential/essential_export_2026-06-05.json")

# --- Ma'lumot bilan to'ldirish ---------------------------------------------
db = SessionLocal()
data = json.load(open(EXPORT))
n_books = n_units = n_words = 0
for b in data["books"][:2]:                       # 2 ta kitob yetarli
    book = Book(name=b.get("name") or f"Book {n_books+1}")
    db.add(book); db.flush(); n_books += 1
    for u in b.get("units", [])[:4]:               # har kitobdan 4 unit
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
user = User(email="test@test.com", name="Test", google_sub="test-sub")
db.add(user); db.commit(); db.refresh(user)
uid = user.id
print(f"Baza: {n_books} kitob, {n_units} unit, {n_words} so'z, user id={uid}\n")

client = TestClient(main.app)
H = {"Authorization": "Bearer " + create_access_token(uid)}
TODAY = date.today()
d = lambda n=0: (TODAY + timedelta(days=n)).isoformat()

FAIL = []
def check(label, cond, detail=""):
    print(("  OK   " if cond else "  XATO ") + label + ("" if cond else f"  -> {detail}"))
    if not cond:
        FAIL.append(label)

# --- 1. Birinchi sessiya ---------------------------------------------------
print("1) Birinchi sessiya — hammasi yangi so'z")
r = client.get("/reviews/today", params={"local_date": d()}, headers=H).json()
items = r["data"]["items"]
check("navbat keldi", r["success"] and len(items) > 0, r)
check("yangi=8, takrorlash=0", r["data"]["new_count"] == 8 and r["data"]["due_count"] == 0, r["data"])
check("hammasi mcq", all(i["exercise"] == "mcq" for i in items))
check("mcq da 4 variant", all(len(i["options"]) == 4 for i in items))
check("to'g'ri javob variantlar ichida",
      all(i["word_en"] in i["options"] for i in items))

pos_ok = 0
for i in items:
    opts = i["options"]
    pos_ok += 1 if len(opts) == 4 else 0
check("distraktorlar to'ldirildi", pos_ok == len(items))

# Hammasiga to'g'ri javob beramiz
answers = [{"word_id": i["word_id"], "exercise": "mcq", "answer": i["word_en"]} for i in items]
r = client.post("/reviews/submit", json={"local_date": d(), "answers": answers}, headers=H).json()
sd = r["data"]
check("8/8 to'g'ri", sd["correct"] == 8 and sd["total"] == 8, sd)
check("streak 1 ga oshdi", sd["streak"]["current_streak"] == 1 and sd["streak"]["increased"], sd["streak"])
check("goal bajarildi", sd["goal_met"] is True)
check("keyingi due 3 kundan keyin", all(x["next_due"] == d(3) for x in sd["results"]),
      [x["next_due"] for x in sd["results"]][:3])

# --- 2. O'sha kuni qayta kirish -------------------------------------------
print("\n2) O'sha kuni qayta ochish — takrorlash qolmagan")
r = client.get("/reviews/today", params={"local_date": d()}, headers=H).json()
check("due=0 (bugungi ish tugadi)", r["data"]["due_count"] == 0, r["data"])
check("yangi so'zlar keladi", r["data"]["new_count"] == 8, r["data"])

r = client.get("/reviews/stats", params={"local_date": d()}, headers=H).json()
st = r["data"]
check("bugun bajarilgan = 8", st["today_done"] == 8, st)
check("stage 0 da 8 ta", st["by_stage"]["0"] == 8, st["by_stage"])
check("aktiv so'z = 0 (Faza 4)", st["active_words"] == 0)

# --- 3. 3 kundan keyin: takrorlash + daraja ko'tarilishi -------------------
print("\n3) 3 kundan keyin — takrorlash keldi, daraja ko'tarilishi kerak")
r = client.get("/reviews/today", params={"local_date": d(3)}, headers=H).json()
items = r["data"]["items"]
due = [i for i in items if i["word_id"] in {a["word_id"] for a in answers}]
check("8 ta takrorlash keldi", r["data"]["due_count"] == 8, r["data"])
check("boshida takrorlash turibdi", items[0]["word_id"] in {a["word_id"] for a in answers})

ans2 = []
for i in items:
    if i["exercise"] == "mcq":
        ans2.append({"word_id": i["word_id"], "exercise": "mcq", "answer": i["word_en"]})
    elif i["exercise"] == "recall_meaning":
        ans2.append({"word_id": i["word_id"], "exercise": "recall_meaning", "known": True})
    else:
        ans2.append({"word_id": i["word_id"], "exercise": "type_production", "answer": i["word_en"]})
r = client.post("/reviews/submit", json={"local_date": d(3), "answers": ans2}, headers=H).json()
sd = r["data"]
check("daraja ko'tarilganlar bor", len(sd["stage_ups"]) == 8, sd["stage_ups"])
# 1 va 2-kunlar o'tkazib yuborilgan -> streak UZILADI va 1 dan boshlanadi
check("2 kun o'tkazilgach streak 1 ga qaytadi",
      sd["streak"]["current_streak"] == 1, sd["streak"])

# Ketma-ket kun: streak oshishi kerak
r = client.get("/reviews/today", params={"local_date": d(4)}, headers=H).json()
a4 = []
for i in r["data"]["items"][:12]:
    if i["exercise"] == "recall_meaning":
        a4.append({"word_id": i["word_id"], "exercise": i["exercise"], "known": True})
    else:
        a4.append({"word_id": i["word_id"], "exercise": i["exercise"], "answer": i["word_en"]})
r = client.post("/reviews/submit", json={"local_date": d(4), "answers": a4}, headers=H).json()
check("ketma-ket kunda streak 2 ga oshadi",
      r["data"]["streak"]["current_streak"] == 2, r["data"]["streak"])

r = client.get("/reviews/today", params={"local_date": d(4)}, headers=H).json()
ex = {i["exercise"] for i in r["data"]["items"] if i["stage"] == 1}
check("1-darajada recall_meaning mashqi", ex == {"recall_meaning"} or not ex, ex)

# --- 4. Xato javob --------------------------------------------------------
print("\n4) Xato javob — daraja pastga, ertaga qaytadi")
r = client.get("/reviews/today", params={"local_date": d(4)}, headers=H).json()
one = [i for i in r["data"]["items"] if i["stage"] >= 1][0]
before = one["stage"]
bad = {"word_id": one["word_id"], "exercise": one["exercise"]}
if one["exercise"] == "recall_meaning":
    bad["known"] = False
else:
    bad["answer"] = "zzzzz"
r = client.post("/reviews/submit", json={"local_date": d(4), "answers": [bad]}, headers=H).json()
res = r["data"]["results"][0]
check("xato deb baholandi", res["correct"] is False, res)
check("daraja bitta pastga", res["stage"] == before - 1, f"{before} -> {res['stage']}")
check("ertaga qaytadi", res["next_due"] == d(5), res)
check("to'g'ri javob qaytarildi", "expected" in res, res)

# --- 5. Imlo toleransi ----------------------------------------------------
print("\n5) Imlo toleransi (type_production)")
db2 = SessionLocal()
from models import UserWord
seen_ids = [x[0] for x in db2.query(UserWord.word_id).filter_by(user_id=uid).all()]
long_word = (
    db2.query(Word)
    .filter(Word.id.notin_(seen_ids), func_len(Word.word_en) > 5)
    .first()
) if False else next(
    w for w in db2.query(Word).filter(Word.id.notin_(seen_ids)).all()
    if len(w.word_en or "") > 5
)
uw = UserWord(user_id=uid, word_id=long_word.id, stage=2, stage_reps=0, step=1,
              ease=250, interval_days=1, due_date=d(10), reps=3, lapses=0)
db2.add(uw); db2.commit()
w = long_word.word_en
typo = w[:-2] + w[-1] + w[-2]          # oxirgi ikki harf o'rin almashdi
r = client.post("/reviews/submit", json={"local_date": d(10), "answers": [
    {"word_id": long_word.id, "exercise": "type_production", "answer": typo}]}, headers=H).json()
res = r["data"]["results"][0]
check(f"transpozitsiya kechiriladi ({w!r} <- {typo!r})", res["correct"] is True, res)

# Butunlay boshqa so'z — kechirilmasligi kerak
uw2 = db2.query(UserWord).filter_by(user_id=uid, word_id=long_word.id).first()
uw2.due_date = d(11); db2.commit()
r = client.post("/reviews/submit", json={"local_date": d(11), "answers": [
    {"word_id": long_word.id, "exercise": "type_production", "answer": "qwertyzz"}]}, headers=H).json()
check("butunlay boshqa javob rad etiladi", r["data"]["results"][0]["correct"] is False,
      r["data"]["results"][0])

# --- 6. STREAK DEVORI — asosiy tekshiruv ----------------------------------
print("\n6) STREAK DEVORI — hamma unit tugagan user ham streak oladi")
db3 = SessionLocal()
u2 = User(email="done@test.com", name="Done", google_sub="done-sub")
db3.add(u2); db3.commit(); db3.refresh(u2)
for unit in db3.query(Unit).all():
    db3.add(UnitCompletion(user_id=u2.id, unit_id=unit.id, score=100))
db3.commit()
H2 = {"Authorization": "Bearer " + create_access_token(u2.id)}

# Eski yo'l: tugatilgan unit quizi streak BERMAYDI (devor)
unit_any = db3.query(Unit).first()
qz = client.get(f"/quiz/unit/{unit_any.id}", params={"count": 5}).json()["data"]
qa = [{"word_id": q["id"], "answer": q["correct"]} for q in qz]
r = client.post("/quiz/submit", json={"source": "quiz", "local_date": d(20),
                                      "unit_id": unit_any.id, "answers": qa}, headers=H2).json()
check("eski quiz yo'li streak bermaydi (devor mavjud edi)",
      r["data"]["streak"]["increased"] is False, r["data"]["streak"])

# Yangi yo'l: takrorlash sessiyasi streak BERADI
rv = client.get("/reviews/today", params={"local_date": d(20)}, headers=H2).json()
its = rv["data"]["items"]
ans3 = [{"word_id": i["word_id"], "exercise": "mcq", "answer": i["word_en"]} for i in its]
r = client.post("/reviews/submit", json={"local_date": d(20), "answers": ans3}, headers=H2).json()
check("YANGI yo'l: takrorlash streak beradi",
      r["data"]["streak"]["increased"] is True and r["data"]["streak"]["current_streak"] == 1,
      r["data"]["streak"])

# --- 7. Migratsiya --------------------------------------------------------
print("\n7) Migratsiya — tugatilgan unitlar stage 1 dan boshlanadi")
db3.query(__import__("models").UserWord).filter_by(user_id=u2.id).delete()
db3.commit()
from migrate_srs import migrate
res = migrate(SessionLocal(), dry_run=True)
check("dry-run yozuv qo'shmaydi", res["would_insert"] > 0, res)
res = migrate(SessionLocal())
check("yozuvlar qo'shildi", res["inserted"] > 0, res)
db4 = SessionLocal()
from models import UserWord as UW
rows = db4.query(UW).filter_by(user_id=u2.id).all()
check("hammasi stage 1", all(x.stage == 1 for x in rows), {x.stage for x in rows})
spread = {x.due_date for x in rows}
check(f"due sanalar yoyilgan ({len(spread)} xil sana)", len(spread) > 5, sorted(spread)[:5])
res2 = migrate(SessionLocal())
check("idempotent (takror qo'shmaydi)", res2["inserted"] == 0, res2)

# --- Yakun ----------------------------------------------------------------
print("\n" + "=" * 60)
if FAIL:
    print(f"XATOLAR ({len(FAIL)}):")
    for f in FAIL:
        print("  - " + f)
    sys.exit(1)
print("HAMMA TEKSHIRUV O'TDI")
