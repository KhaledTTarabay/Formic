import pytest

from conftest import fixed_ticket, new_ticket
from formic.mcp_server import file_ticket


LOGIN_A = ("Login crashes with null user", "login() raises NoneType error in auth.py when the user object is missing")
LOGIN_B = ("Login crashes when user is None", "NoneType exception in login() in auth.py if the user object is missing")
DARK_MODE = ("Dark mode colors wrong on settings page", "The settings page background stays white when dark mode is on")


async def test_files_open_ticket(agent):
    result = await file_ticket(agent, *LOGIN_A, repo="app")
    assert result == {"ticket_id": 1, "status": "open", "possible_duplicates": []}


async def test_stores_all_fields_and_embedding(agent, pool):
    ticket_id = (await file_ticket(
        agent, *LOGIN_A, urgency="high", bug_type="crash", repo="app",
        commit_hash="abc123", file_path="auth.py", line_start=10, line_end=20,
    ))["ticket_id"]
    row = await pool.fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    assert (row["filed_by_agent_id"], row["urgency"], row["bug_type"], row["repo"]) == (agent, "high", "crash", "app")
    assert (row["commit_hash"], row["file_path"], row["line_start"], row["line_end"]) == ("abc123", "auth.py", 10, 20)
    assert row["embedding"] is not None and len(row["embedding"]) == 384


async def test_writes_filed_event(agent, pool):
    ticket_id = await new_ticket(agent, "Crash on save")
    events = await pool.fetch("SELECT event_type, agent_id, content FROM ticket_events WHERE ticket_id = $1", ticket_id)
    assert [tuple(e) for e in events] == [("filed", agent, "Crash on save")]


async def test_similar_ticket_is_suggested_as_duplicate(agent, pool):
    first = (await file_ticket(agent, *LOGIN_A, repo="app"))["ticket_id"]
    second = await file_ticket(agent, *LOGIN_B, repo="app")

    assert [d["ticket_id"] for d in second["possible_duplicates"]] == [first]
    assert second["possible_duplicates"][0]["score"] >= 0.85
    match = await pool.fetchrow("SELECT matched_ticket_id, outcome FROM similarity_matches WHERE ticket_id = $1", second["ticket_id"])
    assert tuple(match) == (first, "pending")


async def test_unrelated_ticket_is_not_suggested(agent):
    await file_ticket(agent, *LOGIN_A, repo="app")
    result = await file_ticket(agent, *DARK_MODE, repo="app")
    assert result["possible_duplicates"] == []


async def test_same_text_in_other_repo_is_not_suggested(agent):
    await file_ticket(agent, *LOGIN_A, repo="app")
    result = await file_ticket(agent, *LOGIN_A, repo="other-repo")
    assert result["possible_duplicates"] == []


async def test_closed_tickets_are_not_suggested(agent):
    await fixed_ticket(agent, LOGIN_A[0], description=LOGIN_A[1], repo="app")
    result = await file_ticket(agent, *LOGIN_B, repo="app")
    assert result["possible_duplicates"] == []


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"title": "   "}, "title must not be empty"),
        ({"description": "  "}, "description must not be empty"),
        ({"line_end": 5}, "line_end requires line_start"),
        ({"line_start": 9, "line_end": 5}, "line_end must be greater than or equal to line_start"),
        ({"line_start": 0}, "line_start must be a positive number"),
    ],
)
async def test_invalid_fields_get_clean_errors(agent, pool, kwargs, message):
    args = {"title": "t", "description": "d", **kwargs}
    with pytest.raises(ValueError, match=message):
        await file_ticket(agent, **args)
    assert await pool.fetchval("SELECT count(*) FROM tickets") == 0
    assert await pool.fetchval("SELECT count(*) FROM ticket_events") == 0


async def test_unknown_agent(agent):
    with pytest.raises(ValueError, match="No agent with id 9999"):
        await file_ticket(9999, "t", "d")


async def test_inactive_agent(inactive_agent):
    with pytest.raises(ValueError, match="not active"):
        await file_ticket(inactive_agent, "t", "d")
