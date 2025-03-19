from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

engine = create_engine("postgresql://postgres:1234@localhost:5432/essantial_db",echo=True)

Base = declarative_base()

session = sessionmaker()