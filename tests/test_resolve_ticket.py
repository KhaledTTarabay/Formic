import pytest

from conftest import claimed_ticket, fixed_ticket, new_ticket
from formic.mcp_server import resolve_ticket


async def test_resolve_marks_fixed(agent, pool):
    ticket_id = await claimed_ticket(agent)
    result = await resolve_ticket(ticket_id, agent, "Added a None guard in login()")

    assert result["ticket_id"] == ticket_id and result["status"] == "fixed"
    assert result["resolved_by_agent_id"] == agent and isinstance(result["fixed_at"], str)
    row = await pool.fetchrow("SELECT fix_description, fixed_at FROM tickets WHERE id = $1", ticket_id)
    assert row["fix_description"] == "Added a None guard in login()" and row["fixed_at"] is not None


@pytest.mark.parametrize("outcome", ["fixed", "wont_fix", "cannot_reproduce"])
async def test_every_outcome(agent, pool, outcome):
    ticket_id = await claimed_ticket(agent)
    result = await resolve_ticket(ticket_id, agent, "reason", outcome=outcome)
    assert result["status"] == outcome
    event = await pool.fetchrow("SELECT event_type, content FROM ticket_events WHERE ticket_id = $1 ORDER BY id DESC LIMIT 1", ticket_id)
    assert tuple(event) == ("resolved", f"{outcome}: reason")


async def test_unclaimed_ticket_cannot_be_resolved(agent):
    ticket_id = await new_ticket(agent)
    with pytest.raises(ValueError, match="is open; only in_progress tickets can be resolved"):
        await resolve_ticket(ticket_id, agent, "x")


async def test_only_claimer_can_resolve(agent, other_agent):
    ticket_id = await claimed_ticket(agent)
    with pytest.raises(ValueError, match=f"claimed by agent {agent}, not you"):
        await resolve_ticket(ticket_id, other_agent, "x")


async def test_cannot_resolve_twice(agent):
    ticket_id = await fixed_ticket(agent)
    with pytest.raises(ValueError, match="is fixed; only in_progress"):
        await resolve_ticket(ticket_id, agent, "again")


async def test_blank_fix_description_rejected(agent, pool):
    ticket_id = await claimed_ticket(agent)
    with pytest.raises(ValueError, match="fix_description must not be empty"):
        await resolve_ticket(ticket_id, agent, "   ")
    assert await pool.fetchval("SELECT status FROM tickets WHERE id = $1", ticket_id) == "in_progress"


async def test_resolve_missing_ticket(agent):
    with pytest.raises(ValueError, match="No ticket with id 9999"):
        await resolve_ticket(9999, agent, "x")


async def test_inactive_agent_cannot_resolve(agent, inactive_agent):
    ticket_id = await claimed_ticket(agent)
    with pytest.raises(ValueError, match="not active"):
        await resolve_ticket(ticket_id, inactive_agent, "x")
