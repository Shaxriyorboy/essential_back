from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
import os

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(DATABASE_URL,echo=True)

Base = declarative_base()

session = sessionmaker()