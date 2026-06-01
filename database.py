from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

engine = create_engine("sqlite:///./test.db",echo=True)

Base = declarative_base()

session = sessionmaker()