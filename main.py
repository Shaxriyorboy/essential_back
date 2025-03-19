from fastapi import FastAPI
from book_routes import book_router
from unit_routes import unit_router
from word_routes import word_router

app = FastAPI()

app.include_router(book_router)
app.include_router(unit_router)
app.include_router(word_router)

@app.get("/")
async def root():
    return {"message": "Bu asosiy sahifa"}
