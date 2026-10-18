import asyncio
import json
import os
from pathlib import Path

# Must be set before formic.db is imported: it reads DATABASE_URL at import time.
TEST_DB = os.environ.get("FORMIC_TEST_DB", "formic_test")
ADMIN_DSN = os.environ.get("FORMIC_TEST_ADMIN_DSN", "postgresql:///template1?host=/var/run/postgresql")
os.environ["DATABASE_URL"] = os.environ.get(
    "FORMIC_TEST_DSN", f"postgresql:///{TEST_DB}?host=/var/run/postgresql"
)

import asyncpg
import pytest
import pytest_asyncio
from pytest_asyncio import is_async_test

from formic import db, embeddings
from formic.mcp_server import claim_ticket, file_ticket, mcp, resolve_ticket

SCHEMA = Path(__file__).resolve().parent.parent / "schema.sql"

if "test" not in TEST_DB:
    raise RuntimeError(f"Refusing to run tests against {TEST_DB!r}: the test database is dropped and recreated")


def pytest_collection_modifyitems(items):
    # Run every async test on one session-wide event loop, so they can share
    # the asyncpg pool and the loaded embedding model.
    marker = pytest.mark.asyncio(loop_scope="session")
    for item in items:
        if is_async_test(item):
            item.add_marker(marker, append=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def database():
    admin = await asyncpg.connect(ADMIN_DSN)
    await admin.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}"')
    await admin.execute(f'CREATE DATABASE "{TEST_DB}"')
    await admin.close()

    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    await conn.execute(SCHEMA.read_text())
    await conn.close()

    await db.connect()
    await asyncio.to_thread(embeddings.load)
    yield
    await db.disconnect()

    admin = await asyncpg.connect(ADMIN_DSN)
    await admin.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}"')
    await admin.close()


@pytest_asyncio.fixture(autouse=True)
async def clean_tables():
    await db.get_pool().execute(
        "TRUNCATE ticket_events, similarity_matches, tickets, agents RESTART IDENTITY CASCADE"
    )


@pytest.fixture
def pool():
    return db.get_pool()


async def _make_agent(name: str, active: bool = True) -> int:
    return await db.get_pool().fetchval(
        "INSERT INTO agents (name, developer, is_active) VALUES ($1, 'tests', $2) RETURNING id",
        name, active,
    )


@pytest_asyncio.fixture
async def agent():
    return await _make_agent("agent")


@pytest_asyncio.fixture
async def other_agent():
    return await _make_agent("other")


@pytest_asyncio.fixture
async def inactive_agent():
    return await _make_agent("inactive", active=False)


async def new_ticket(agent_id: int, title: str = "Some bug", **kwargs) -> int:
    kwargs.setdefault("description", f"{title}: steps to reproduce")
    return (await file_ticket(agent_id, title, **kwargs))["ticket_id"]


async def claimed_ticket(agent_id: int, title: str = "Some bug", **kwargs) -> int:
    ticket_id = await new_ticket(agent_id, title, **kwargs)
    await claim_ticket(ticket_id, agent_id)
    return ticket_id


async def fixed_ticket(fixer_id: int, title: str = "Some bug", **kwargs) -> int:
    ticket_id = await claimed_ticket(fixer_id, title, **kwargs)
    await resolve_ticket(ticket_id, fixer_id, "the fix")
    return ticket_id


async def call_tool(name: str, arguments: dict) -> dict:
    """Call a tool through FastMCP, so arguments go through its Pydantic validation."""
    result = await mcp.call_tool(name, arguments)
    if isinstance(result, tuple):
        result = result[1]
    if isinstance(result, list):
        # Content blocks: the agent receives the result as JSON text.
        result = json.loads(result[0].text)
    if isinstance(result, dict) and set(result) == {"result"}:
        result = result["result"]
    return result
