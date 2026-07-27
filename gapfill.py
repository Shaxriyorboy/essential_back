"""Gap-fill (In context) uchun misol gapdan so'zni topib olib tashlash.

Ma'lumot tahlili (3600 so'z ustida):
    72.6%  so'z gapda aynan o'zi
    26.0%  o'zgargan shaklda (hunt -> hunted, reply -> replied)
     1.5%  umuman topilmadi (noto'g'ri fe'llar + OCR axlati)

Shuning uchun AI kerak emas — oddiy shakl moslashtirish 98.5% ni qoplaydi.
Topilmagan 1.5% uchun `build_gap()` None qaytaradi va chaqiruvchi o'sha so'zga
boshqa mashq beradi.
"""
import re

# Noto'g'ri fe'llar — muntazam qoidalar bilan topilmaydiganlari.
IRREGULAR = {
    "be": ["is", "am", "are", "was", "were", "been", "being"],
    "begin": ["began", "begun"], "break": ["broke", "broken"],
    "bring": ["brought"], "build": ["built"], "buy": ["bought"],
    "catch": ["caught"], "choose": ["chose", "chosen"], "come": ["came"],
    "cut": ["cut"], "do": ["did", "done", "does"], "draw": ["drew", "drawn"],
    "drink": ["drank", "drunk"], "drive": ["drove", "driven"],
    "eat": ["ate", "eaten"], "fall": ["fell", "fallen"], "feel": ["felt"],
    "fight": ["fought"], "find": ["found"], "fly": ["flew", "flown"],
    "forget": ["forgot", "forgotten"], "get": ["got", "gotten"],
    "give": ["gave", "given"], "go": ["went", "gone", "goes"],
    "grow": ["grew", "grown"], "hang": ["hung"], "have": ["had", "has"],
    "hear": ["heard"], "hide": ["hid", "hidden"], "hit": ["hit"],
    "hold": ["held"], "keep": ["kept"], "know": ["knew", "known"],
    "lead": ["led"], "leave": ["left"], "lend": ["lent"], "lose": ["lost"],
    "make": ["made"], "mean": ["meant"], "meet": ["met"], "pay": ["paid"],
    "put": ["put"], "read": ["read"], "ride": ["rode", "ridden"],
    "ring": ["rang", "rung"], "rise": ["rose", "risen"], "run": ["ran"],
    "say": ["said"], "see": ["saw", "seen"], "sell": ["sold"],
    "send": ["sent"], "shake": ["shook", "shaken"], "shine": ["shone"],
    "shoot": ["shot"], "show": ["showed", "shown"], "sing": ["sang", "sung"],
    "sink": ["sank", "sunk"], "sit": ["sat"], "sleep": ["slept"],
    "speak": ["spoke", "spoken"], "spend": ["spent"], "stand": ["stood"],
    "steal": ["stole", "stolen"], "strike": ["struck"], "swim": ["swam", "swum"],
    "take": ["took", "taken"], "teach": ["taught"], "tear": ["tore", "torn"],
    "tell": ["told"], "think": ["thought"], "throw": ["threw", "thrown"],
    "understand": ["understood"], "wake": ["woke", "woken"],
    "wear": ["wore", "worn"], "win": ["won"], "write": ["wrote", "written"],
}

PLACEHOLDER = "_____"


def word_forms(word: str) -> list:
    """So'zning gapda uchrashi mumkin bo'lgan shakllari (uzundan qisqaga).

    Uzundan qisqaga tartiblanadi: `hunted` ni `hunt` dan oldin sinash kerak,
    aks holda gapdan faqat "hunt" qismi kesilib, "ed" osilib qoladi.
    """
    w = (word or "").strip().lower()
    if not w:
        return []
    out = {w, w + "s", w + "es", w + "ed", w + "d", w + "ing", w + "'s"}
    if w.endswith("y") and len(w) > 2:
        out |= {w[:-1] + "ies", w[:-1] + "ied", w[:-1] + "ier", w[:-1] + "iest"}
    if w.endswith("e"):
        out |= {w[:-1] + "ing", w[:-1] + "ed"}
    if len(w) > 3 and w[-1] not in "aeiouwxy":
        out |= {w + w[-1] + "ing", w + w[-1] + "ed"}
    out |= set(IRREGULAR.get(w, []))
    return sorted(out, key=len, reverse=True)


def build_gap(word_en: str, example: str):
    """Gapdan so'zni topib, o'rniga katak qo'yadi.

    Qaytadi: `{"sentence": "...", "answer": "hunted", "base": "hunt"}`
    Topilmasa `None` — chaqiruvchi boshqa mashq berishi kerak.
    """
    if not word_en or not example:
        return None
    sentence = example.strip()
    for form in word_forms(word_en):
        # `\b` bilan — "hunt" ni "hunter" ichidan topmasin
        pattern = re.compile(r"\b" + re.escape(form) + r"\b", re.IGNORECASE)
        match = pattern.search(sentence)
        if match:
            return {
                "sentence": sentence[:match.start()] + PLACEHOLDER
                + sentence[match.end():],
                "answer": match.group(0),
                "base": word_en.strip(),
            }
    return None
