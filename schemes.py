from pydantic import BaseModel
from typing import List, Optional


class QuizAnswerItem(BaseModel):
    word_id: int
    answer: str   # foydalanuvchi tanlagan variant (word_en)


class QuizSubmitModel(BaseModel):
    source: str = "quiz"          # "quiz" | "ai"
    local_date: str               # client mahalliy sanasi "YYYY-MM-DD"
    unit_id: Optional[int] = None  # qaysi unit quizi — completion uchun kerak
    answers: List[QuizAnswerItem]

    class Config:
        json_schema_extra = {
            "example": {
                "source": "quiz",
                "local_date": "2026-06-04",
                "unit_id": 1,
                "answers": [
                    {"word_id": 1, "answer": "apple"},
                    {"word_id": 2, "answer": "book"},
                ],
            }
        }


class DeviceRegisterModel(BaseModel):
    token: str                          # FCM registration token
    platform: Optional[str] = None      # "android" | "ios"
    timezone: Optional[str] = None      # IANA zona, masalan "Asia/Tashkent"

    class Config:
        json_schema_extra = {
            "example": {
                "token": "fcm-registration-token...",
                "platform": "android",
                "timezone": "Asia/Tashkent",
            }
        }


class DeviceUnregisterModel(BaseModel):
    token: str

    class Config:
        json_schema_extra = {
            "example": {"token": "fcm-registration-token..."}
        }


class GoogleAuthModel(BaseModel):
    id_token: str

    class Config:
        json_schema_extra = {
            "example": {
                "id_token": "eyJhbGciOi... (Google Sign-In dan olingan id_token)"
            }
        }


class RefreshModel(BaseModel):
    refresh_token: str

    class Config:
        json_schema_extra = {
            "example": {"refresh_token": "long-random-refresh-token"}
        }


class AppleAuthModel(BaseModel):
    identity_token: str             # Apple'dan olingan identityToken (JWT)
    raw_nonce: Optional[str] = None  # nonce tekshiruvi uchun (xom holatda)
    # Apple ism/email'ni FAQAT birinchi kirishda beradi — client uzatadi.
    name: Optional[str] = None
    email: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "identity_token": "eyJhbGciOi... (Apple Sign-In identityToken)",
                "raw_nonce": "random-nonce",
                "name": "Shaxriyor Tursunaliyev",
                "email": "user@privaterelay.appleid.com",
            }
        }


class BookModel(BaseModel):
    name: str

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "name": "Essential 1",
            }
        }


class UnitModel(BaseModel):
    book_id: Optional[int] = None
    name: str
    history: str

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "name": "Unit 1",
                "history": "example history",
                "book_id": 1,
            }
        }


class WordModel(BaseModel):
    word_en: str
    word_uz: str
    comment: Optional[str] = None
    definition: str
    phonetic: str
    example: str
    word_classes: str
    isFavorite: bool = False
    unit_id: int

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "word_en": "apple",
                "word_uz": "olma",
                "comment": "",
                "unit_id": 1,
                "definition": "a round fruit",
                "phonetic": "ˈæp.əl",
                "example": "I ate an apple.",
                "word_classes": "noun",
                "isFavorite": False,
            }
        }
