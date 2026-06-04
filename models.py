from datetime import datetime, timezone

from database import Base
from sqlalchemy import Column, Integer, Text, Boolean, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy_utils.types import ChoiceType


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)

    # Google Sign-In ma'lumotlari
    google_sub = Column(String, unique=True, index=True, nullable=True)  # Google'dagi unique id
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