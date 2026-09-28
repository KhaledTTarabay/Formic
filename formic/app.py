from contextlib import asynccontextmanager
from fastapi import FastAPI
from formic import db

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    yield
    await db.disconnect()


app = FastAPI(title = "Formic", lifespan=lifespan)


@app.get("/health")
async def health_check():
    result = await db.get_pool().fetchval("SELECT 1")
    return {"status": "ok", "db": result == 1}