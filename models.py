from datetime import datetime, timezone

from database import Base
from sqlalchemy import Column, Integer, Text, Boolean, String, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy_utils.types import ChoiceType


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)

    # Google Sign-In ma'lumotlari
    google_sub = Column(String, unique=True, index=True, nullable=True)  # Google'dagi unique id
    # Apple Sign-In ma'lumoti (Apple'dagi unique `sub`)
    apple_sub = Column(String, unique=True, index=True, nullable=True)
    email = Column(String, unique=True, index=True, nullable=True)
    name = Column(String, nullable=True)
    picture = Column(String, nullable=True)

    # Auth manbasi — hozir "google", kelajakda "phone" (SMS) qo'shiladi
    auth_provider = Column(String, default="google")
    phone = Column(String, unique=True, nullable=True)
    password_hash = Column(String, nullable=True)

    is_admin = Column(Boolean, default=False)

    # Streak (Bosqich 1) — ustunlarni hozir qo'shamiz, keyin migratsiya kerak bo'lmasin
    current_streak = Column(Integer, default=0)
    longest_streak = Column(Integer, default=0)
    last_active_date = Column(String, nullable=True)  # local sana, ISO "YYYY-MM-DD"

    # AI Speaking tarifi. "free" | "pro" | "premium". Kunlik vaqt limiti shunга
    # qarab beriladi (TIER_DAILY_SECONDS). tier_expires_at — oylik obuna tugash
    # sanasi (None = bepul/cheksiz). Tugagach avtomatik "free"ga qaytadi.
    tier = Column(String, default="free")
    tier_expires_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class StreakDay(Base):
    """Foydalanuvchi ma'lum bir kunni "yopgan"ligini bildiradi (streak uchun).

    local_date — foydalanuvchining O'Z mahalliy sanasi ("YYYY-MM-DD"), client
    yuboradi (vaqt zonasi har kim uchun o'ziga mos bo'lishi uchun).
    Har bir (user, local_date) uchun bitta yozuv — kunni quiz YOKI ai yopadi.
    """
    __tablename__ = 'streak_days'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), index=True)
    local_date = Column(String, index=True)   # "YYYY-MM-DD" (client local)
    source = Column(String)                    # "quiz" | "ai"
    score = Column(Integer, default=0)         # foiz (0-100)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint('user_id', 'local_date', name='uq_user_localdate'),
    )


class UnitCompletion(Base):
    """Foydalanuvchi ma'lum bir unitni tugatganini bildiradi.

    Unit quizini >=80% topshirilganda yoziladi. Har (user, unit) uchun bitta
    yozuv — bir marta tugatilgach o'zgarmaydi. Kitob "tugatilgan"ligi alohida
    saqlanmaydi — kitobdagi barcha unit complete bo'lsa, hisoblab chiqariladi.
    """
    __tablename__ = 'unit_completions'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), index=True)
    unit_id = Column(Integer, ForeignKey('unit.id'), index=True)
    score = Column(Integer, default=0)   # birinchi tugatgandagi natija (foiz)
    completed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint('user_id', 'unit_id', name='uq_user_unit'),
    )


class Device(Base):
    """Foydalanuvchining push (FCM) qurilmasi.

    Login bo'lganda ilova FCM tokenini shu yerga ro'yxatdan o'tkazadi
    (`POST /devices`). Server streak eslatmalarini shu tokenlarga yuboradi.
    `token` unique — bitta qurilma bitta yozuv. Qurilma egasi o'zgarsa
    (boshqa akkaunt kirsa) `user_id` yangilanadi.
    """
    __tablename__ = 'devices'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), index=True)
    token = Column(String, unique=True, index=True)   # FCM registration token
    platform = Column(String, nullable=True)          # "android" | "ios"
    timezone = Column(String, nullable=True)          # IANA zona, masalan "Asia/Tashkent"
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class UserFavorite(Base):
    """Foydalanuvchining saralangan so'zi (per-user). Word.isFavorite global
    maydon o'rniga — har bir foydalanuvchining o'z favoritesi."""
    __tablename__ = 'user_favorites'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), index=True)
    word_id = Column(Integer, ForeignKey('word.id'), index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint('user_id', 'word_id', name='uq_user_word_fav'),
    )


class WordComment(Base):
    """Foydalanuvchining so'zga yozgan shaxsiy izohi (per-user, faqat o'zi ko'radi).
    Word.comment global maydon o'rniga — ommaviy UGC emas."""
    __tablename__ = 'word_comments'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), index=True)
    word_id = Column(Integer, ForeignKey('word.id'), index=True)
    text = Column(String)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint('user_id', 'word_id', name='uq_user_word_comment'),
    )


class RefreshToken(Base):
    """Refresh token (uzoq muddat). Access token tugaganda client shu orqali
    yangi access token oladi. DB'da SAQLANADI (hash) — shuning uchun bekor
    qilish mumkin (logout, hisob o'chirish, barcha qurilmalardan chiqish).
    """
    __tablename__ = 'refresh_tokens'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), index=True)
    token_hash = Column(String, unique=True, index=True)  # sha256(raw_token)
    expires_at = Column(DateTime)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Book(Base):
    __tablename__ = 'book'
    id = Column(Integer,primary_key=True)
    name = Column(String)
    unit = relationship("Unit", back_populates="book")

class Unit(Base):
    __tablename__ = 'unit'
    id = Column(Integer,primary_key=True)
    name = Column(String)
    history = Column(String)
    book_id = Column(Integer, ForeignKey('book.id'))
    book = relationship("Book", back_populates="unit")
    word = relationship("Word",back_populates='unit')

class AiUsage(Base):
    """AI speaking partnyor uchun kunlik foydalanish hisoblagichi (per-user).

    Bepul Gemini kvotasi (API kalit bo'yicha UMUMIY ~1500/kun) ni himoya qilish
    uchun har foydalanuvchiga kunlik xabar limiti qo'yiladi. `date` — server
    UTC sanasi ("YYYY-MM-DD"). Har (user, date) uchun bitta yozuv.
    Bu YANGI jadval — `create_all` uni avtomatik yaratadi (qo'lda migratsiya kerakmas).
    """
    __tablename__ = 'ai_usage'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), index=True)
    date = Column(String, index=True)   # foydalanuvchi mahalliy sanasi "YYYY-MM-DD"
    count = Column(Integer, default=0)            # xabarlar soni (statistika uchun)
    seconds_used = Column(Integer, default=0)     # shu kun ishlatilgan AI vaqt (soniya)

    __table_args__ = (
        UniqueConstraint('user_id', 'date', name='uq_ai_usage_user_date'),
    )


class Word(Base):
    __tablename__ = 'word'
    id = Column(Integer, primary_key=True)
    word_en = Column(String)
    word_uz = Column(String)
    comment = Column(String,nullable=True)
    definition = Column(String)
    phonetic = Column(String)
    example = Column(String)
    word_classes = Column(String)
    isFavorite = Column(Boolean,default=False)
    unit_id = Column(Integer, ForeignKey('unit.id'))
    unit = relationship("Unit", back_populates='word')