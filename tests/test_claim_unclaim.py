import pytest

from conftest import claimed_ticket, fixed_ticket, new_ticket
from formic.mcp_server import claim_ticket, unclaim_ticket


async def test_claim_moves_ticket_to_in_progress(agent, pool):
    ticket_id = await new_ticket(agent)
    result = await claim_ticket(ticket_id, agent, note="will add a guard")

    assert result["ticket_id"] == ticket_id and result["status"] == "in_progress"
    assert isinstance(result["claimed_at"], str)
    row = await pool.fetchrow("SELECT claimed_by_agent_id, claimed_at FROM tickets WHERE id = $1", ticket_id)
    assert row["claimed_by_agent_id"] == agent and row["claimed_at"] is not None
    event = await pool.fetchrow("SELECT event_type, content FROM ticket_events WHERE ticket_id = $1 ORDER BY id DESC LIMIT 1", ticket_id)
    assert tuple(event) == ("claimed", "will add a guard")


async def test_cannot_claim_twice(agent, other_agent):
    ticket_id = await claimed_ticket(agent)
    with pytest.raises(ValueError, match="is in_progress and cannot be claimed"):
        await claim_ticket(ticket_id, other_agent)


async def test_cannot_claim_closed_ticket(agent):
    ticket_id = await fixed_ticket(agent)
    with pytest.raises(ValueError, match="is fixed and cannot be claimed"):
        await claim_ticket(ticket_id, agent)


async def test_claim_missing_ticket(agent):
    with pytest.raises(ValueError, match="No ticket with id 9999"):
        await claim_ticket(9999, agent)


async def test_inactive_agent_cannot_claim(agent, inactive_agent):
    ticket_id = await new_ticket(agent)
    with pytest.raises(ValueError, match="not active"):
        await claim_ticket(ticket_id, inactive_agent)


async def test_unclaim_reopens_and_clears_claim(agent, pool):
    ticket_id = await claimed_ticket(agent)
    result = await unclaim_ticket(ticket_id, agent, note="tried patching auth.py, root cause is in the ORM")

    assert result == {"ticket_id": ticket_id, "status": "open"}
    row = await pool.fetchrow("SELECT claimed_by_agent_id, claimed_at FROM tickets WHERE id = $1", ticket_id)
    assert row["claimed_by_agent_id"] is None and row["claimed_at"] is None
    event = await pool.fetchrow("SELECT event_type, content FROM ticket_events WHERE ticket_id = $1 ORDER BY id DESC LIMIT 1", ticket_id)
    assert tuple(event) == ("unclaimed", "tried patching auth.py, root cause is in the ORM")


async def test_unclaimed_ticket_can_be_claimed_again(agent, other_agent):
    ticket_id = await claimed_ticket(agent)
    await unclaim_ticket(ticket_id, agent, note="stuck")
    result = await claim_ticket(ticket_id, other_agent)
    assert result["status"] == "in_progress"


async def test_only_claimer_can_unclaim(agent, other_agent):
    ticket_id = await claimed_ticket(agent)
    with pytest.raises(ValueError, match=f"claimed by agent {agent}, not you"):
        await unclaim_ticket(ticket_id, other_agent, note="x")


async def test_cannot_unclaim_open_ticket(agent):
    ticket_id = await new_ticket(agent)
    with pytest.raises(ValueError, match="only in_progress tickets can be unclaimed"):
        await unclaim_ticket(ticket_id, agent, note="x")


async def test_unclaim_missing_ticket(agent):
    with pytest.raises(ValueError, match="No ticket with id 9999"):
        await unclaim_ticket(9999, agent, note="x")


@pytest.mark.parametrize("note", ["", "   "])
async def test_unclaim_requires_note(agent, pool, note):
    ticket_id = await claimed_ticket(agent)
    with pytest.raises(ValueError, match="note is required"):
        await unclaim_ticket(ticket_id, agent, note=note)
    assert await pool.fetchval("SELECT status FROM tickets WHERE id = $1", ticket_id) == "in_progress"


async def test_deactivated_agent_can_still_release_its_claim(agent, pool):
    # Intentional: an agent deactivated after claiming may give its tickets back.
    ticket_id = await claimed_ticket(agent)
    await pool.execute("UPDATE agents SET is_active = false WHERE id = $1", agent)
    result = await unclaim_ticket(ticket_id, agent, note="being shut down")
    assert result["status"] == "open"
