"""SRS (Spaced Repetition System) algoritmi — SRS_SPEC.md, 3-bo'lim.

Bu yerdagi funksiyalar SOF: DB'ga ham, FastAPI'ga ham bog'liq emas. Shu sababli
test yozish oson va mantiqni endpointdan alohida tekshirib bo'ladi.

Asosiy g'oya: har so'zning DARAJASI (stage) bor va daraja qaysi mashq
berilishini belgilaydi. To'g'ri javob darajani ko'taradi va takrorlash oralig'ini
cho'zadi; xato javob bir pog'ona pastga tushiradi va ertaga qaytaradi.
"""
import re
from datetime import date, timedelta

# --- Sozlanadigan parametrlar (SRS_SPEC.md, 12-bo'lim) ---------------------

INTERVALS = [1, 3, 7, 16, 35, 90]   # kun — `step` shu massivga indeks
STAGE_UP_THRESHOLD = 2              # darajani oshirish uchun ketma-ket to'g'ri
# Daraja ko'tarilganda `step` shuncha orqaga tortiladi.
# SABAB: yangi daraja = YANGI, QIYINROQ mashq turi. Agar interval uzun bo'lib
# qolsa, so'z 2-darajaga (yozish) chiqadi-yu, keyingi safar 40 kundan keyin
# ko'rinadi — ya'ni ishlab chiqarish mashqi deyarli bajarilmaydi. Holbuki
# Faza 1 ning butun qiymati aynan o'sha mashqda. Shuning uchun har yangi
# darajada qisqa intervaldan qayta boshlanadi.
STAGE_UP_STEP_BACK = 2

# So'z MAX darajaga yetguncha O'SHA KUNI qayta-qayta chiqadi (kun oralig'isiz).
# Ya'ni xohlagan foydalanuvchi bitta kunda so'zni Recognise -> Recall -> Produce
# gacha olib chiqa oladi.
#
# ESLATMA (mahsulot qarori): xotira nuqtai nazaridan takrorlashlar orasida kun
# oralig'i bo'lgani kuchliroq eslab qolishni beradi. Bu yerda ataylab tezlik
# tanlangan — foydalanuvchini "yetar, ertaga kel" deb to'xtatmaslik uchun.
# Oqibati: daraja raqamlari qisman faollikni ham aks ettiradi.
# MAX darajaga yetgach normal SRS oraliqlari ishlaydi.
SAME_DAY_UNTIL_MAX_STAGE = True
EASE_START, EASE_MIN, EASE_MAX = 250, 130, 300
MAX_STAGE_PHASE1 = 2                # Faza 1 da 2-darajadan yuqoriga chiqmaymiz
TYPO_TOLERANCE_MIN_LEN = 5          # shu uzunlikdan katta so'zlarda 1 xato kechiriladi

# Daraja -> mashq turi. Client shu satrga qarab qaysi widget'ni ko'rsatishini
# hal qiladi. 3 va 4-darajalar Faza 3/4 da yoqiladi.
EXERCISE_BY_STAGE = {
    0: "mcq",              # 4 variantli test (UZ -> EN)
    1: "recall_meaning",   # karta + o'zini baholash (EN -> UZ)
    2: "type_production",  # yozish (UZ -> EN)  <- passiv/aktiv chegarasi
    3: "gap_fill",         # Faza 3
    4: "speaking",         # Faza 4
}


def exercise_for_stage(stage: int) -> str:
    return EXERCISE_BY_STAGE.get(stage, "mcq")


# --- Sana yordamchilari ----------------------------------------------------

def parse_date(s: str):
    """ "YYYY-MM-DD" -> date. Noto'g'ri bo'lsa None (streak.py bilan bir xil)."""
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def add_days(local_date: str, days: int) -> str:
    """ "YYYY-MM-DD" + kun -> "YYYY-MM-DD". Sana buzuq bo'lsa o'zini qaytaradi."""
    d = parse_date(local_date)
    if d is None:
        return local_date
    return (d + timedelta(days=days)).isoformat()


# --- Javobni baholash ------------------------------------------------------

def normalize(s) -> str:
    """Yozma javobni solishtirish uchun tozalaydi: kichik harf, tinish belgilari
    olib tashlanadi, ortiqcha bo'shliqlar bittaga tushiriladi."""
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z' ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _edit_distance(a: str, b: str) -> int:
    """Damerau-Levenshtein masofasi — qo'shni harflar ALMASHIB ketishini ham
    bitta xato deb sanaydi.

    Oddiy Levenshtein `recieve` -> `receive` ni 2 ta xato deb hisoblaydi, holbuki
    bu eng ko'p uchraydigan imlo xatosi turi (ikki harf o'rin almashishi).
    Shuning uchun transpozitsiyani qo'shamiz.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    la, lb = len(a), len(b)
    # d[i][j] — a[:i] va b[:j] orasidagi masofa
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j

    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(
                d[i - 1][j] + 1,        # o'chirish
                d[i][j - 1] + 1,        # qo'shish
                d[i - 1][j - 1] + cost,  # almashtirish
            )
            # transpozitsiya: "ie" <-> "ei"
            if (i > 1 and j > 1
                    and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]):
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[la][lb]


def is_answer_correct(given, expected) -> bool:
    """Yozma javob to'g'rimi.

    Uzun so'zlarda 1 ta harf xatosi kechiriladi: `recieve` deb yozgan odam
    so'zni BILADI, uni jazolash mashqni asabiylashtiradi va tark etishga olib
    keladi. Qisqa so'zlarda kechirilmaydi — u yerda 1 harf butunlay boshqa
    so'z bo'lib qolishi mumkin (cat/cut, hat/hot).
    """
    g, e = normalize(given), normalize(expected)
    if not e:
        return False
    if g == e:
        return True
    if len(e) > TYPO_TOLERANCE_MIN_LEN:
        return _edit_distance(g, e) <= 1
    return False


# --- Rejalashtirish yadrosi ------------------------------------------------

def initial_state(local_date: str) -> dict:
    """Birinchi marta ko'rilayotgan so'z uchun boshlang'ich holat.

    `due_date = local_date` — so'z o'sha kuniyoq sessiyaga tushadi.
    """
    return {
        "stage": 0,
        "stage_reps": 0,
        "step": 0,
        "ease": EASE_START,
        "interval_days": 0,
        "due_date": local_date,
        "reps": 0,
        "lapses": 0,
    }


def next_state(current: dict, correct: bool, local_date: str,
               max_stage: int = MAX_STAGE_PHASE1) -> dict:
    """Javobdan keyingi yangi holatni hisoblaydi.

    `current` — kamida stage/stage_reps/step/ease/reps/lapses kalitlari bo'lgan
    dict (UserWord qatoridan yoki `initial_state` dan).

    Qaytadi: yangi qiymatlar dict'i (chaqiruvchi uni modelga yozadi).
    """
    stage = int(current.get("stage") or 0)
    stage_reps = int(current.get("stage_reps") or 0)
    step = int(current.get("step") or 0)
    ease = int(current.get("ease") or EASE_START)
    reps = int(current.get("reps") or 0)
    lapses = int(current.get("lapses") or 0)

    reps += 1

    if correct:
        stage_reps += 1
        ease = min(ease + 10, EASE_MAX)
        step = min(step + 1, len(INTERVALS) - 1)

        # Yetarli marta to'g'ri javob berilgan bo'lsa — keyingi darajaga.
        # Yangi daraja = yangi mashq turi, shuning uchun interval qisqaradi
        # (STAGE_UP_STEP_BACK izohiga qarang).
        if stage_reps >= STAGE_UP_THRESHOLD and stage < max_stage:
            stage += 1
            stage_reps = 0
            step = max(step - STAGE_UP_STEP_BACK, 0)

        interval_days = max(1, round(INTERVALS[step] * ease / EASE_START))
    else:
        lapses += 1
        stage_reps = 0
        ease = max(ease - 20, EASE_MIN)
        step = max(step - 2, 0)
        # MUHIM: daraja NOLGA tushmaydi, faqat bitta pog'ona pastga.
        # Nolga tushirish jazolovchi va foydalanuvchini yo'qotadi.
        stage = max(stage - 1, 0)
        interval_days = 1

    # So'z hali MAX darajaga yetmagan bo'lsa — O'SHA KUNI qayta chiqadi.
    # Shu tufayli foydalanuvchi xohlasa bitta o'tirishda so'zni Recognise dan
    # Produce gacha olib chiqa oladi va hech qanday "ertaga kel" to'sig'i yo'q.
    # MAX darajaga yetgach normal oraliqlar boshlanadi (uzoq muddatli saqlanish).
    if SAME_DAY_UNTIL_MAX_STAGE and stage < max_stage:
        interval_days = 0

    return {
        "stage": stage,
        "stage_reps": stage_reps,
        "step": step,
        "ease": ease,
        "interval_days": interval_days,
        "due_date": add_days(local_date, interval_days),
        "reps": reps,
        "lapses": lapses,
    }
