import pytest

from conftest import claimed_ticket, fixed_ticket, new_ticket
from formic.mcp_server import file_ticket, mark_duplicate


async def test_marks_duplicate_and_confirms_suggestion(agent, pool):
    original = (await file_ticket(agent, "Login crashes with null user", "login() raises NoneType error in auth.py when user is missing", repo="app"))["ticket_id"]
    copy = await file_ticket(agent, "Login crashes when user is None", "NoneType exception in login() in auth.py if the user object is missing", repo="app")
    assert original in [d["ticket_id"] for d in copy["possible_duplicates"]]

    result = await mark_duplicate(copy["ticket_id"], original, agent, note="same NoneType crash")

    assert result == {"ticket_id": copy["ticket_id"], "status": "duplicate", "duplicate_of": original}
    outcome = await pool.fetchval("SELECT outcome FROM similarity_matches WHERE ticket_id = $1 AND matched_ticket_id = $2", copy["ticket_id"], original)
    assert outcome == "confirmed"
    event = await pool.fetchrow("SELECT event_type, content FROM ticket_events WHERE ticket_id = $1 ORDER BY id DESC LIMIT 1", copy["ticket_id"])
    assert tuple(event) == ("marked_duplicate", "same NoneType crash")


async def test_works_without_a_suggestion(agent):
    a = await new_ticket(agent, "Cache bug")
    b = await new_ticket(agent, "Payment rounding")
    result = await mark_duplicate(b, a, agent)
    assert result["duplicate_of"] == a


async def test_follows_duplicate_to_its_original(agent):
    original = await new_ticket(agent, "Original")
    copy = await new_ticket(agent, "Copy")
    third = await new_ticket(agent, "Third")
    await mark_duplicate(copy, original, agent)

    result = await mark_duplicate(third, copy, agent)
    assert result["duplicate_of"] == original


async def test_self_duplicate_rejected(agent):
    a = await new_ticket(agent)
    with pytest.raises(ValueError, match="cannot be a duplicate of itself"):
        await mark_duplicate(a, a, agent)


async def test_loop_back_to_self_rejected(agent):
    x = await new_ticket(agent, "X")
    y = await new_ticket(agent, "Y")
    await mark_duplicate(y, x, agent)
    with pytest.raises(ValueError, match="cannot be a duplicate of itself"):
        await mark_duplicate(x, y, agent)


async def test_in_progress_ticket_can_be_marked(agent):
    original = await new_ticket(agent, "Original")
    ticket_id = await claimed_ticket(agent, "Being worked on")
    result = await mark_duplicate(ticket_id, original, agent)
    assert result["status"] == "duplicate"


@pytest.mark.parametrize("closed", ["fixed", "duplicate"])
async def test_closed_ticket_cannot_be_marked(agent, closed):
    original = await new_ticket(agent, "Original")
    if closed == "fixed":
        ticket_id = await fixed_ticket(agent, "Done")
    else:
        ticket_id = await new_ticket(agent, "Already dup")
        await mark_duplicate(ticket_id, original, agent)
    with pytest.raises(ValueError, match=f"is {closed} and cannot be marked as a duplicate"):
        await mark_duplicate(ticket_id, original, agent)


async def test_missing_original(agent):
    a = await new_ticket(agent)
    with pytest.raises(ValueError, match="No ticket with id 9999"):
        await mark_duplicate(a, 9999, agent)


async def test_missing_ticket(agent):
    a = await new_ticket(agent)
    with pytest.raises(ValueError, match="No ticket with id 9999"):
        await mark_duplicate(9999, a, agent)


async def test_inactive_agent(agent, inactive_agent):
    a = await new_ticket(agent, "A")
    b = await new_ticket(agent, "B")
    with pytest.raises(ValueError, match="not active"):
        await mark_duplicate(b, a, inactive_agent)


async def test_failed_mark_writes_nothing(agent, pool):
    a = await new_ticket(agent)
    before = await pool.fetchval("SELECT count(*) FROM ticket_events")
    with pytest.raises(ValueError):
        await mark_duplicate(a, a, agent, note="should roll back")
    assert await pool.fetchval("SELECT count(*) FROM ticket_events") == before
    assert await pool.fetchval("SELECT status FROM tickets WHERE id = $1", a) == "open"
