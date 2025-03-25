from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

engine = create_engine("postgresql://essantial_db_user:vXE5tcxMWN6TcXwGFpCmpLQyw7iN1NZU@dpg-cvgous2n91rc73a7i4a0-a.oregon-postgres.render.com/essantial_db",echo=True)

Base = declarative_base()

session = sessionmaker()