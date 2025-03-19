from database import Base, engine
from models import Book,Word, Unit

Base.metadata.create_all(bind=engine)