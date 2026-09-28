import os
import asyncpg

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql:///formic?host=/var/run/postgresql")

_pool: asyncpg.Pool | None = None

async def connect() -> None:
    global _pool
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)


async def disconnect() -> None:
    if _pool is not None:
        await _pool.close()


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized.")
    return _pool