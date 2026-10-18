import pytest

from conftest import claimed_ticket, fixed_ticket, new_ticket
from formic.mcp_server import claim_ticket, verify_ticket


async def test_passed_marks_verified(agent, other_agent, pool):
    ticket_id = await fixed_ticket(agent)
    result = await verify_ticket(ticket_id, other_agent, True, note="ran it, no crash")

    assert result["ticket_id"] == ticket_id and result["status"] == "verified"
    assert isinstance(result["verified_at"], str)
    row = await pool.fetchrow("SELECT verified_by_agent_id, resolved_by_agent_id, fix_description FROM tickets WHERE id = $1", ticket_id)
    assert tuple(row) == (other_agent, agent, "the fix")
    event = await pool.fetchrow("SELECT event_type, content FROM ticket_events WHERE ticket_id = $1 ORDER BY id DESC LIMIT 1", ticket_id)
    assert tuple(event) == ("verified", "ran it, no crash")


async def test_failed_reopens_and_clears_fix(agent, other_agent, pool):
    ticket_id = await fixed_ticket(agent)
    result = await verify_ticket(ticket_id, other_agent, False, note="still crashes on empty cache")

    assert result == {"ticket_id": ticket_id, "status": "open"}
    row = await pool.fetchrow(
        "SELECT claimed_by_agent_id, claimed_at, resolved_by_agent_id, fix_description, fixed_at FROM tickets WHERE id = $1",
        ticket_id,
    )
    assert all(value is None for value in row.values())
    events = await pool.fetch("SELECT event_type, content FROM ticket_events WHERE ticket_id = $1 ORDER BY id", ticket_id)
    assert [e["event_type"] for e in events] == ["filed", "claimed", "resolved", "reopened"]
    assert events[2]["content"] == "fixed: the fix"
    assert events[3]["content"] == "still crashes on empty cache"


async def test_reopened_ticket_can_be_claimed_again(agent, other_agent):
    ticket_id = await fixed_ticket(agent)
    await verify_ticket(ticket_id, other_agent, False, note="still broken")
    result = await claim_ticket(ticket_id, other_agent)
    assert result["status"] == "in_progress"


@pytest.mark.parametrize("passed", [True, False])
async def test_resolver_cannot_verify_own_fix(agent, pool, passed):
    ticket_id = await fixed_ticket(agent)
    with pytest.raises(ValueError, match="another agent must verify it"):
        await verify_ticket(ticket_id, agent, passed, note="x")
    assert await pool.fetchval("SELECT status FROM tickets WHERE id = $1", ticket_id) == "fixed"


@pytest.mark.parametrize("make", ["open", "in_progress", "verified"])
async def test_only_fixed_tickets_can_be_verified(agent, other_agent, make):
    if make == "open":
        ticket_id = await new_ticket(agent)
    elif make == "in_progress":
        ticket_id = await claimed_ticket(agent)
    else:
        ticket_id = await fixed_ticket(agent)
        await verify_ticket(ticket_id, other_agent, True)
    with pytest.raises(ValueError, match=f"is {make}; only fixed tickets can be verified"):
        await verify_ticket(ticket_id, other_agent, True)


@pytest.mark.parametrize("note", [None, "", "   "])
async def test_failing_requires_note(agent, other_agent, pool, note):
    ticket_id = await fixed_ticket(agent)
    with pytest.raises(ValueError, match="note is required"):
        await verify_ticket(ticket_id, other_agent, False, note=note)
    assert await pool.fetchval("SELECT status FROM tickets WHERE id = $1", ticket_id) == "fixed"


async def test_passing_does_not_require_note(agent, other_agent):
    ticket_id = await fixed_ticket(agent)
    result = await verify_ticket(ticket_id, other_agent, True)
    assert result["status"] == "verified"


async def test_verify_missing_ticket(agent):
    with pytest.raises(ValueError, match="No ticket with id 9999"):
        await verify_ticket(9999, agent, True)


async def test_inactive_agent_cannot_verify(agent, inactive_agent):
    ticket_id = await fixed_ticket(agent)
    with pytest.raises(ValueError, match="not active"):
        await verify_ticket(ticket_id, inactive_agent, True)
