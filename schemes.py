from pydantic import BaseModel
from typing import Optional

class BookModel(BaseModel):
    name: str

class Config:
        orm_mode = True
        schema_exrta = {
            "example": {
                "name": "Essantial 1",
        }
    }

class UnitModel(BaseModel):
    book_id: Optional[int]
    name: str
    history: str

class Config:
        orm_mode = True
        schema_extra = {
            'example': {
                'name': 'Unit 1',
                'history': 'example history',
                'book_id': 1
            }
        }

class WordModel(BaseModel):
      word_en: str
      word_uz: str
      comment: str
      definition: str
      phonetic: str
      example: str
      word_classes: str
      isFavorite: bool
      unit_id: int

class Config:
        orm_mode = True
        schema_extra = {
            'example': {
                'word_en': 'Unit 1',
                'word_uz': 'example',
                'comment': '',
                'unit_id': 1,
                'definition': '',
                'phonetic': '',
                'example': '',
                'word_classes': '',
                'isFavorite': False,
            }
        }