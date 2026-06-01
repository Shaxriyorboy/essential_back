import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Baza manzili environment variable'dan olinadi.
# DATABASE_URL berilmagan bo'lsa (lokalda) — SQLite ishlatiladi.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./test.db")

# Neon/Render ba'zan 'postgres://' ko'rinishida beradi,
# SQLAlchemy 2.0 esa 'postgresql://' kutadi — to'g'rilaymiz.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# SQLite ko'p threadli FastAPI'da ishlashi uchun maxsus argument kerak.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,   # uzilib qolgan ulanishlarni avtomatik tiklaydi (Neon uchun muhim)
    connect_args=connect_args,
)

Base = declarative_base()

# Har bir so'rov uchun yangi session yaratuvchi factory
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    """FastAPI dependency: har so'rovga alohida session beradi va so'rov
    tugagach yopadi. Bu global session 'buzilgan transaction' muammosini
    (bitta xato keyingi barcha so'rovlarni 500 qilishi) hal qiladi."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
