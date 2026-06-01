from pydantic import BaseModel
from typing import Optional


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
