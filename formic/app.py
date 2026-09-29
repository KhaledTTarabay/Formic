from contextlib import asynccontextmanager
from fastapi import FastAPI
from formic import db
from formic.mcp_server import mcp

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    try:
        async with mcp.session_manager.run():
            yield
    finally:
        await db.disconnect()


app = FastAPI(title = "Formic", lifespan=lifespan)
app.mount("/mcp", mcp.streamable_http_app())


@app.get("/health")
async def health_check():
    result = await db.get_pool().fetchval("SELECT 1")
    return {"status": "ok", "db": result == 1}