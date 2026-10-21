import asyncio
import asyncpg
from pathlib import Path
from formic import db

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
MIGRATION_LOCK_ID = 4242

async def apply_migrations(conn: asyncpg.Connection) -> list[str]:
    await conn.execute("SELECT pg_advisory_lock($1)", MIGRATION_LOCK_ID)
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        applied = {
            row["version"]
            for row in await conn.fetch("SELECT version FROM schema_migrations")
        }

        pending = [
            path for path in sorted(MIGRATIONS_DIR.glob("*.sql"))
            if path.stem not in applied
        ]

        newly_applied = []
        for path in pending:
            async with conn.transaction():
                await conn.execute(path.read_text())
                await conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES ($1)", path.stem
                )
            newly_applied.append(path.stem)
        return newly_applied
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", MIGRATION_LOCK_ID)

async def main() -> None:
    conn = await asyncpg.connect(db.DATABASE_URL)
    try:
        applied = await apply_migrations(conn)
    finally:
        await conn.close()

    if applied:
        for version in applied:
            print(f"applied {version}")

    else:
        print("database is already up to date")

if __name__ == "__main__":
    asyncio.run(main())