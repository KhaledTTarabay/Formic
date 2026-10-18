import json

import pytest

from conftest import claimed_ticket, fixed_ticket, new_ticket
from formic.mcp_server import get_ticket, list_tickets, unclaim_ticket


async def insert_ticket(pool, agent, title, urgency="normal", status="open", **extra):
    """Insert directly, skipping embeddings, for tests that need many tickets fast."""
    columns = ["title", "description", "urgency", "status", "filed_by_agent_id", *extra]
    values = [title, "d", urgency, status, agent, *extra.values()]
    placeholders = ", ".join(f"${i}" for i in range(1, len(values) + 1))
    return await pool.fetchval(
        f"INSERT INTO tickets ({', '.join(columns)}) VALUES ({placeholders}) RETURNING id", *values
    )


# ---- list_tickets ----

async def test_default_lists_only_open_tickets(agent):
    open_id = await new_ticket(agent, "Open one")
    await claimed_ticket(agent, "Claimed one")
    result = await list_tickets()
    assert [t["id"] for t in result["tickets"]] == [open_id]
    assert result["count"] == 1


async def test_status_none_lists_everything(agent):
    await new_ticket(agent, "A")
    await claimed_ticket(agent, "B")
    await fixed_ticket(agent, "C")
    result = await list_tickets(status=None)
    assert sorted(t["status"] for t in result["tickets"]) == ["fixed", "in_progress", "open"]


async def test_sorted_by_urgency_then_oldest(agent, pool):
    low = await insert_ticket(pool, agent, "low", urgency="low")
    normal_old = await insert_ticket(pool, agent, "normal old", urgency="normal")
    critical = await insert_ticket(pool, agent, "critical", urgency="critical")
    normal_new = await insert_ticket(pool, agent, "normal new", urgency="normal")
    high = await insert_ticket(pool, agent, "high", urgency="high")
    await pool.execute("UPDATE tickets SET created_at = created_at + interval '1 minute' WHERE id = $1", normal_new)

    ids = [t["id"] for t in (await list_tickets())["tickets"]]
    assert ids == [critical, high, normal_old, normal_new, low]


@pytest.mark.parametrize(
    "filter_kwargs, matching",
    [
        ({"urgency": "critical"}, {"urgency": "critical"}),
        ({"bug_type": "crash"}, {"bug_type": "crash"}),
        ({"repo": "app"}, {"repo": "app"}),
        ({"file_path": "auth.py"}, {"file_path": "auth.py"}),
    ],
)
async def test_filters(agent, pool, filter_kwargs, matching):
    hit = await insert_ticket(pool, agent, "hit", **{k: v for k, v in matching.items() if k != "urgency"},
                              urgency=matching.get("urgency", "normal"))
    await insert_ticket(pool, agent, "miss")
    result = await list_tickets(**filter_kwargs)
    assert [t["id"] for t in result["tickets"]] == [hit]


async def test_filter_by_claimer(agent, other_agent):
    mine = await claimed_ticket(agent, "Mine")
    await claimed_ticket(other_agent, "Theirs")
    result = await list_tickets(status="in_progress", claimed_by_agent_id=agent)
    assert [t["id"] for t in result["tickets"]] == [mine]


async def test_filters_combine_with_and(agent, pool):
    both = await insert_ticket(pool, agent, "both", urgency="high", repo="app")
    await insert_ticket(pool, agent, "only urgency", urgency="high", repo="other")
    await insert_ticket(pool, agent, "only repo", urgency="low", repo="app")
    result = await list_tickets(urgency="high", repo="app")
    assert [t["id"] for t in result["tickets"]] == [both]


async def test_paging(agent, pool):
    ids = [await insert_ticket(pool, agent, f"t{i}") for i in range(5)]
    first = await list_tickets(limit=2)
    second = await list_tickets(limit=2, offset=2)
    last = await list_tickets(limit=2, offset=4)
    assert [t["id"] for t in first["tickets"]] == ids[:2]
    assert [t["id"] for t in second["tickets"]] == ids[2:4]
    assert [t["id"] for t in last["tickets"]] == ids[4:]


async def test_limit_is_capped_at_100(agent, pool):
    for i in range(105):
        await insert_ticket(pool, agent, f"t{i}")
    assert (await list_tickets(limit=500))["count"] == 100


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": -5}, {"offset": -1}])
async def test_invalid_paging_rejected(kwargs):
    with pytest.raises(ValueError, match="limit must be at least 1"):
        await list_tickets(**kwargs)


async def test_summaries_leave_out_long_fields(agent):
    await new_ticket(agent)
    ticket = (await list_tickets())["tickets"][0]
    assert set(ticket) == {"id", "title", "status", "urgency", "bug_type", "repo", "file_path", "claimed_by_agent_id", "created_at"}
    assert isinstance(ticket["created_at"], str)
    json.dumps(ticket)


async def test_empty_result(agent):
    assert await list_tickets() == {"tickets": [], "count": 0}


async def test_filter_values_are_not_sql(agent, pool):
    await insert_ticket(pool, agent, "t", repo="app")
    result = await list_tickets(repo="x' OR '1'='1")
    assert result["count"] == 0
    assert await pool.fetchval("SELECT count(*) FROM tickets") == 1


# ---- get_ticket ----

async def test_get_ticket_returns_details_and_history(agent, other_agent):
    ticket_id = await new_ticket(agent, "Crash on save", repo="app", file_path="save.py", line_start=3)
    await claim_ticket_and_release(ticket_id, other_agent)

    result = await get_ticket(ticket_id)
    ticket = result["ticket"]
    assert ticket["id"] == ticket_id and ticket["title"] == "Crash on save"
    assert ticket["description"] == "Crash on save: steps to reproduce"
    assert (ticket["repo"], ticket["file_path"], ticket["line_start"]) == ("app", "save.py", 3)
    assert ticket["status"] == "open" and ticket["filed_by_agent_id"] == agent
    assert [(e["event_type"], e["agent_id"]) for e in result["events"]] == [
        ("filed", agent), ("claimed", other_agent), ("unclaimed", other_agent)
    ]
    assert result["events"][2]["content"] == "gave up"


async def claim_ticket_and_release(ticket_id, agent_id):
    from formic.mcp_server import claim_ticket
    await claim_ticket(ticket_id, agent_id)
    await unclaim_ticket(ticket_id, agent_id, note="gave up")


async def test_get_ticket_timestamps_and_nulls(agent):
    ticket_id = await new_ticket(agent)
    result = await get_ticket(ticket_id)
    ticket = result["ticket"]
    assert isinstance(ticket["created_at"], str)
    assert ticket["claimed_at"] is None and ticket["fixed_at"] is None and ticket["verified_at"] is None
    assert all(isinstance(e["created_at"], str) for e in result["events"])
    assert "embedding" not in ticket
    json.dumps(result)


async def test_get_fixed_ticket_shows_fix(agent):
    ticket_id = await fixed_ticket(agent)
    ticket = (await get_ticket(ticket_id))["ticket"]
    assert ticket["status"] == "fixed" and ticket["fix_description"] == "the fix"
    assert isinstance(ticket["fixed_at"], str) and ticket["resolved_by_agent_id"] == agent


async def test_get_missing_ticket():
    with pytest.raises(ValueError, match="No ticket with id 9999"):
        await get_ticket(9999)
