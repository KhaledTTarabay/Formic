"""Tools called through FastMCP, the way agents call them.

FastMCP builds a Pydantic model from each tool's signature and validates the
agent's arguments against it before the tool runs. These tests cover that
layer: the schemas agents see, rejected arguments, and results that must
serialize to JSON.
"""
import json

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from conftest import call_tool, fixed_ticket, new_ticket
from formic.mcp_server import mcp

TOOLS = {
    "file_ticket": {"agent_id", "title", "description"},
    "claim_ticket": {"ticket_id", "agent_id"},
    "unclaim_ticket": {"ticket_id", "agent_id", "note"},
    "resolve_ticket": {"ticket_id", "agent_id", "fix_description"},
    "mark_duplicate": {"ticket_id", "duplicate_of", "agent_id"},
    "verify_ticket": {"ticket_id", "agent_id", "passed"},
    "list_tickets": set(),
    "get_ticket": {"ticket_id"},
}


@pytest.fixture
async def tools():
    return {t.name: t for t in await mcp.list_tools()}


# ---- schemas agents see ----

async def test_all_tools_registered(tools):
    assert set(tools) == set(TOOLS)


@pytest.mark.parametrize("name", TOOLS)
async def test_every_tool_has_a_docstring(tools, name):
    assert tools[name].description and len(tools[name].description) > 100


@pytest.mark.parametrize("name, required", TOOLS.items())
async def test_required_arguments(tools, name, required):
    assert set(tools[name].inputSchema.get("required", [])) == required


def enum_values(prop):
    if "enum" in prop:
        return prop["enum"]
    for option in prop.get("anyOf", []):
        if "enum" in option:
            return option["enum"]
    return None


@pytest.mark.parametrize(
    "tool, arg, values",
    [
        ("file_ticket", "urgency", ["low", "normal", "high", "critical"]),
        ("file_ticket", "bug_type", ["bug", "crash", "regression", "test_failure", "build_failure", "performance", "security"]),
        ("resolve_ticket", "outcome", ["fixed", "wont_fix", "cannot_reproduce"]),
        ("list_tickets", "status", ["open", "in_progress", "fixed", "wont_fix", "cannot_reproduce", "duplicate", "verified"]),
        ("list_tickets", "urgency", ["low", "normal", "high", "critical"]),
    ],
)
async def test_enums_in_schema(tools, tool, arg, values):
    assert enum_values(tools[tool].inputSchema["properties"][arg]) == values


async def test_defaults_in_schema(tools):
    props = tools["file_ticket"].inputSchema["properties"]
    assert props["urgency"]["default"] == "normal" and props["bug_type"]["default"] == "bug"
    assert tools["resolve_ticket"].inputSchema["properties"]["outcome"]["default"] == "fixed"
    list_props = tools["list_tickets"].inputSchema["properties"]
    assert list_props["status"]["default"] == "open" and list_props["limit"]["default"] == 20


# ---- arguments Pydantic rejects before the tool runs ----

@pytest.mark.parametrize(
    "tool, arguments, field",
    [
        ("file_ticket", {"agent_id": 1, "title": "t", "description": "d", "urgency": "urgent"}, "urgency"),
        ("file_ticket", {"agent_id": 1, "title": "t", "description": "d", "bug_type": "typo"}, "bug_type"),
        ("file_ticket", {"agent_id": "abc", "title": "t", "description": "d"}, "agent_id"),
        ("file_ticket", {"title": "t", "description": "d"}, "agent_id"),
        ("file_ticket", {"agent_id": 1, "title": "t", "description": "d", "line_start": "ten"}, "line_start"),
        ("claim_ticket", {"ticket_id": 1}, "agent_id"),
        ("unclaim_ticket", {"ticket_id": 1, "agent_id": 1}, "note"),
        ("resolve_ticket", {"ticket_id": 1, "agent_id": 1, "fix_description": "f", "outcome": "done"}, "outcome"),
        ("mark_duplicate", {"ticket_id": 1, "agent_id": 1}, "duplicate_of"),
        ("verify_ticket", {"ticket_id": 1, "agent_id": 1, "passed": "maybe"}, "passed"),
        ("list_tickets", {"status": "closed"}, "status"),
        ("list_tickets", {"limit": "lots"}, "limit"),
        ("get_ticket", {"ticket_id": "one"}, "ticket_id"),
    ],
)
async def test_invalid_arguments_rejected(pool, tool, arguments, field):
    with pytest.raises(ToolError, match=field):
        await call_tool(tool, arguments)
    assert await pool.fetchval("SELECT count(*) FROM tickets") == 0


# ---- results through the MCP layer ----

async def test_tool_errors_reach_agent_cleanly(agent):
    with pytest.raises(ToolError, match="title must not be empty"):
        await call_tool("file_ticket", {"agent_id": agent, "title": "  ", "description": "d"})


async def test_full_flow_through_mcp(agent, other_agent):
    filed = await call_tool("file_ticket", {"agent_id": agent, "title": "Crash on save", "description": "save() raises"})
    ticket_id = filed["ticket_id"]
    assert (await call_tool("claim_ticket", {"ticket_id": ticket_id, "agent_id": agent}))["status"] == "in_progress"
    assert (await call_tool("resolve_ticket", {"ticket_id": ticket_id, "agent_id": agent, "fix_description": "guard"}))["status"] == "fixed"
    assert (await call_tool("verify_ticket", {"ticket_id": ticket_id, "agent_id": other_agent, "passed": True}))["status"] == "verified"


@pytest.mark.parametrize("tool", ["list_tickets", "get_ticket"])
async def test_read_results_serialize_to_json(agent, other_agent, tool):
    ticket_id = await fixed_ticket(agent)
    await new_ticket(agent, "Another")
    arguments = {"status": None} if tool == "list_tickets" else {"ticket_id": ticket_id}
    result = await call_tool(tool, arguments)
    json.dumps(result)
    if tool == "list_tickets":
        assert result["count"] == 2
    else:
        assert result["ticket"]["status"] == "fixed" and len(result["events"]) == 3


async def test_status_null_accepted_through_mcp(agent):
    await new_ticket(agent)
    result = await call_tool("list_tickets", {"status": None})
    assert result["count"] == 1
