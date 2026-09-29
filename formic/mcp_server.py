from mcp.server.fastmcp import FastMCP
from formic import db
from typing import Literal
import asyncpg

mcp = FastMCP("Formic MCP", stateless_http=True, streamable_http_path="/")

CHECK_MESSAGES = {
    "tickets_line_start_check": "line_start must be a positive number",
    "tickets_line_end_check": "line_end must be a positive number",
    "tickets_line_range_check": "line_end must be greater than or equal to line_start",
    "tickets_line_end_needs_start_check": "line_end requires line_start",
}

@mcp.tool()
async def file_ticket(
    agent_id:int, 
    title:str, 
    description:str, 
    urgency:Literal["low","normal","high","critical"] = "normal", 
    bug_type:Literal["bug","crash","regression","test_failure", "build_failure", "performance", "security"] = "bug",
    repo:str | None = None,
    commit_hash:str | None = None,
    file_path:str | None = None,
    line_start:int | None = None,
    line_end:int | None = None,
    )-> dict:
    """This is a function you call when you want to file a ticket"""

    
    try:
        ticket_id = await db.get_pool().fetchval(
            """
            INSERT INTO tickets (
                filed_by_agent_id, title, description, urgency, bug_type, repo,
                commit_hash, file_path, line_start, line_end
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
            """,
            agent_id, title, description, urgency, bug_type, 
            repo, commit_hash, file_path, line_start, line_end,

        )
    except asyncpg.ForeignKeyViolationError:
        raise ValueError(f"No agent with id {agent_id}")
    except asyncpg.CheckViolationError as e:
        raise ValueError(CHECK_MESSAGES.get(e.constraint_name, "Invalid ticket data"))

    
    return {"ticket_id": ticket_id,"status": "open"}   

