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
from device_routes import device_router
from database import Base, engine

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)

app.include_router(auth_router)
app.include_router(book_router)
app.include_router(unit_router)
app.include_router(word_router)
app.include_router(quiz_router)
app.include_router(stats_router)
app.include_router(data_router)
app.include_router(progress_router)
app.include_router(device_router)
app.include_router(account_router)

@app.get("/")
async def root():
    return {"message": "Bu asosiy sahifa"}
