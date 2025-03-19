from database import Base
from sqlalchemy import Column, Integer, Text, Boolean, String, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy_utils.types import ChoiceType

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