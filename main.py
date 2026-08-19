from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from auth_routes import auth_router, account_router
from book_routes import book_router
from unit_routes import unit_router
from word_routes import word_router
from quiz_routes import quiz_router
from stats_routes import stats_router
from data_routes import data_router
from progress_routes import progress_router
from review_routes import review_router
from streak_routes import streak_router
from device_routes import device_router
from speaking_routes import speaking_router
from telegram_routes import telegram_router, ensure_webhook
from database import Base, engine
from sqlalchemy import text

app = FastAPI()


def _ensure_schema():
    """Mavjud bazaga yangi ustunlarni qo'shadi (Alembic yo'q — yengil migratsiya).

    `create_all` mavjud jadvalga ustun qo'shmaydi, shuning uchun yangi
    `users.apple_sub` ustunini qo'lda, idempotent tarzda qo'shamiz."""
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "postgresql":
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS apple_sub VARCHAR"))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_apple_sub "
                "ON users (apple_sub)"))
            # AI tarif ustunlari
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS tier VARCHAR DEFAULT 'free'"))
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS tier_expires_at TIMESTAMP"))
            # Streak muzlatgichi hisobi
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS streak_freezes INTEGER DEFAULT 0"))
            # AI kunlik vaqt hisobi (ai_usage jadvali mavjud bo'lsa)
            conn.execute(text(
                "ALTER TABLE ai_usage ADD COLUMN IF NOT EXISTS seconds_used INTEGER DEFAULT 0"))
            # SRS: kunlik navbat so'rovi (user_id + due_date) tez bo'lishi uchun
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_user_words_due "
                "ON user_words (user_id, due_date)"))
        elif dialect == "sqlite":
            ucols = [r[1] for r in conn.execute(text("PRAGMA table_info(users)"))]
            if "apple_sub" not in ucols:
                conn.execute(text("ALTER TABLE users ADD COLUMN apple_sub VARCHAR"))
            if "tier" not in ucols:
                conn.execute(text("ALTER TABLE users ADD COLUMN tier VARCHAR DEFAULT 'free'"))
            if "tier_expires_at" not in ucols:
                conn.execute(text("ALTER TABLE users ADD COLUMN tier_expires_at TIMESTAMP"))
            if "streak_freezes" not in ucols:
                conn.execute(text("ALTER TABLE users ADD COLUMN streak_freezes INTEGER DEFAULT 0"))
            acols = [r[1] for r in conn.execute(text("PRAGMA table_info(ai_usage)"))]
            if acols and "seconds_used" not in acols:
                conn.execute(text("ALTER TABLE ai_usage ADD COLUMN seconds_used INTEGER DEFAULT 0"))
            # SRS: kunlik navbat so'rovi (user_id + due_date) tez bo'lishi uchun
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_user_words_due "
                "ON user_words (user_id, due_date)"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)
_ensure_schema()

app.include_router(auth_router)
app.include_router(book_router)
app.include_router(unit_router)
app.include_router(word_router)
app.include_router(quiz_router)
app.include_router(stats_router)
app.include_router(data_router)
app.include_router(progress_router)
app.include_router(review_router)
app.include_router(streak_router)
app.include_router(device_router)
app.include_router(speaking_router)
app.include_router(account_router)
app.include_router(telegram_router)


@app.on_event("startup")
def _on_startup():
    # Telegram webhook'ni Render URL'iga avtomatik ulaydi (token bo'lsa).
    ensure_webhook()


@app.get("/")
async def root():
    return {"message": "Bu asosiy sahifa"}
