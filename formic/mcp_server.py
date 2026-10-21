from mcp.server.fastmcp import FastMCP
from formic import db
from formic import queries
from formic import embeddings
from typing import Literal
import asyncpg

mcp = FastMCP("Formic MCP", stateless_http=True, streamable_http_path="/")

CHECK_MESSAGES = {
    "tickets_line_start_check": "line_start must be a positive number",
    "tickets_line_end_check": "line_end must be a positive number",
    "tickets_line_range_check": "line_end must be greater than or equal to line_start",
    "tickets_line_end_needs_start_check": "line_end requires line_start",
    "tickets_title_not_blank_check": "title must not be empty",
    "tickets_description_not_blank_check": "description must not be empty",
    "tickets_fix_description_not_blank_check": "fix_description must not be empty",
    "tickets_not_self_duplicate_check": "a ticket cannot be a duplicate of itself",
    "tickets_verifier_not_resolver_check": "you cannot verify a ticket you resolved",
}

DUPLICATE_THRESHOLD = 0.85


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
    # Docstring written by an AI assistant (Claude).
    """File a new bug ticket for a defect you found but are not fixing right now.

    Use this when you hit a bug, crash, failing test, broken build, performance
    problem or security issue that should be tracked so you or another agent
    can fix it later. To fix a ticket yourself, file it and then claim it.

    Args:
        agent_id: Your agent id. The agent must exist and be active.
        title: Short one-line summary of the problem. Must not be blank.
        description: What happened, how to reproduce it, and expected vs.
            actual behaviour. Include error messages or stack traces if you
            have them. Must not be blank.
        urgency: How soon this needs fixing: "low", "normal" (default),
            "high" or "critical".
        bug_type: The kind of problem: "bug" (default), "crash",
            "regression", "test_failure", "build_failure", "performance"
            or "security".
        repo: Repository where the bug lives, if known.
        commit_hash: Commit where you saw the bug, if known.
        file_path: Path to the file with the suspect code, relative to the
            repo root.
        line_start: First suspect line (1-based, must be positive).
        line_end: Last suspect line. Requires line_start and must be
            greater than or equal to it. Omit for a single line.

    Returns:
        {"ticket_id": int, "status": "open"}

    Raises:
        ValueError: If the agent doesn't exist or is inactive, or if a field
            is invalid. The message says what to fix.
    """

    pool = db.get_pool()
    embedding = (await embeddings.embed([f"{title}\n{description}"]))[0]

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                is_active = await conn.fetchval("SELECT is_active FROM agents WHERE id = $1", agent_id)
                if is_active is None:
                    raise ValueError(f"No agent with id {agent_id}")
                if not is_active:
                    raise ValueError(f"Agent with id {agent_id} is not active and cannot file tickets")
                
                row = await conn.fetchrow(
                    """
                    INSERT INTO tickets (
                        filed_by_agent_id, title, description, urgency, bug_type, repo,
                        commit_hash, file_path, line_start, line_end, embedding
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    RETURNING id, status
                    """,
                    agent_id, title, description, urgency, bug_type, 
                    repo, commit_hash, file_path, line_start, line_end, embedding,
                )

                neighbours = await conn.fetch(
                    """
                    SELECT id, 1 - (embedding <=> $1) AS score
                    FROM tickets
                    WHERE id <> $2
                    AND status IN ('open', 'in_progress')
                    AND repo IS NOT DISTINCT FROM $3
                    AND embedding IS NOT NULL
                    ORDER BY embedding <=> $1
                    LIMIT 5
                    """,
                    embedding, row["id"], repo,
                )
                matches = [n for n in neighbours if n["score"] >= DUPLICATE_THRESHOLD]

                await conn.executemany(
                    """
                    INSERT INTO similarity_matches (ticket_id, matched_ticket_id, similarity_score)
                    VALUES ($1, $2, $3)
                    """,
                    [(row["id"], m["id"], m["score"]) for m in matches]
                )


                await conn.execute(
                    """
                    INSERT INTO ticket_events (ticket_id, agent_id, event_type, content)
                    VALUES ($1, $2, 'filed', $3)
                    """,

                    row["id"], agent_id, title,
                )

    except asyncpg.ForeignKeyViolationError:
        raise ValueError(f"No agent with id {agent_id}")
    except asyncpg.CheckViolationError as e:
        raise ValueError(CHECK_MESSAGES.get(e.constraint_name, "Invalid ticket data"))

    return {
        "ticket_id": row["id"],
        "status": row["status"],
        "possible_duplicates": [{"ticket_id": m["id"], "score": round(m["score"], 3)} for m in matches],
    }


@mcp.tool()
async def claim_ticket(ticket_id:int, agent_id:int, note:str | None = None) -> dict:
    # Docstring written by an AI assistant (Claude).
    """Claim an open ticket so you can work on fixing it.

    Claiming moves the ticket from "open" to "in_progress" and records you as
    the agent working on it, so other agents know not to pick it up. Only
    open tickets can be claimed. If another agent claimed it first, you get
    an error and should pick a different ticket.

    Args:
        ticket_id: The id of the ticket to claim.
        agent_id: Your agent id. The agent must exist and be active.
        note: Optional short note on how you plan to fix it. It is saved in
            the ticket's history.

    Returns:
        {"ticket_id": int, "status": "in_progress", "claimed_at": ISO 8601 timestamp}

    Raises:
        ValueError: If the agent doesn't exist or is inactive, the ticket
            doesn't exist, or the ticket is not open (the message includes
            its current status).
    """
    pool = db.get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                is_active = await conn.fetchval("SELECT is_active FROM agents WHERE id = $1", agent_id)
                if is_active is None:
                    raise ValueError(f"No agent with id {agent_id}")
                if not is_active:
                    raise ValueError(f"Agent with id {agent_id} is not active and cannot claim tickets")
                
                row = await conn.fetchrow(
                    """
                    UPDATE tickets
                    SET status = 'in_progress', claimed_by_agent_id = $2, claimed_at = NOW()
                    WHERE id = $1 AND status = 'open'
                    RETURNING id, status, claimed_at
                    """,
                    ticket_id, agent_id
                )

                if row is None:
                    status = await conn.fetchval("SELECT status FROM tickets WHERE id = $1", ticket_id)
                    if status is None:
                        raise ValueError(f"No ticket with id {ticket_id}")
                    raise ValueError(f"Ticket {ticket_id} is {status} and cannot be claimed")

                await conn.execute(
                    """
                    INSERT INTO ticket_events (ticket_id, agent_id, event_type, content)
                    VALUES ($1, $2, 'claimed', $3)
                    """,
                    ticket_id, agent_id, note,
                )
    except asyncpg.ForeignKeyViolationError:
        raise ValueError(f"No agent with id {agent_id}")

    return {"ticket_id": row["id"],
            "status": row["status"],
            "claimed_at": row["claimed_at"].isoformat()}           


@mcp.tool()
async def resolve_ticket(
    ticket_id:int, 
    agent_id:int, 
    fix_description:str,
    outcome: Literal["fixed", "wont_fix", "cannot_reproduce"] = "fixed",
    ) -> dict:
    # Docstring written by an AI assistant (Claude).
    """Close a ticket you claimed: mark it fixed, won't fix, or can't reproduce.

    Only the agent that claimed the ticket can resolve it, and only while it
    is "in_progress". Call claim_ticket first if you haven't.

    Args:
        ticket_id: The id of the ticket to resolve.
        agent_id: Your agent id. Must be the agent that claimed the ticket.
        fix_description: For "fixed", what was wrong and what you changed
            (files touched, commit hash). For "wont_fix" or
            "cannot_reproduce", why. Must not be blank.
        outcome: How the ticket ends: "fixed" (default), "wont_fix" or
            "cannot_reproduce".

    Returns:
        {"ticket_id": int, "status": outcome, "resolved_by_agent_id": int,
         "fixed_at": ISO 8601 timestamp}

    Raises:
        ValueError: If the agent doesn't exist or is inactive, the ticket
            doesn't exist, is not in progress, or is claimed by another
            agent, or if fix_description is blank.
    """
    pool = db.get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                is_active = await conn.fetchval("SELECT is_active FROM agents WHERE id = $1", agent_id)
                if is_active is None:
                    raise ValueError(f"No agent with id {agent_id}")
                if not is_active:
                    raise ValueError(f"Agent with id {agent_id} is not active and cannot resolve tickets")
                
                row = await conn.fetchrow(
                    """
                    UPDATE tickets
                    SET status = $4, resolved_by_agent_id = $2,
                        fix_description = $3, fixed_at = NOW()
                    WHERE id = $1 AND status = 'in_progress' AND claimed_by_agent_id = $2
                    RETURNING id, status, resolved_by_agent_id, fixed_at
                    """,
                    ticket_id, agent_id, fix_description, outcome,
                )

                if row is None:
                    info = await conn.fetchrow(
                        "SELECT status, claimed_by_agent_id FROM tickets WHERE id = $1", ticket_id
                    )
                    if info is None:
                        raise ValueError(f"No ticket with id {ticket_id}")
                    if info["status"] != "in_progress":
                        raise ValueError(
                            f"Ticket {ticket_id} is {info['status']}; only in_progress tickets can be resolved"
                        )
                    raise ValueError(
                        f"Ticket {ticket_id} is claimed by agent {info['claimed_by_agent_id']}, not you"
                    )

                await conn.execute(
                    """
                    INSERT INTO ticket_events (ticket_id, agent_id, event_type, content)
                    VALUES ($1, $2, 'resolved', $3)
                    """,
                    ticket_id, agent_id, f"{outcome}: {fix_description}",
                )
    except asyncpg.ForeignKeyViolationError:
        raise ValueError(f"No agent with id {agent_id}")
    except asyncpg.CheckViolationError as e:
        raise ValueError(CHECK_MESSAGES.get(e.constraint_name, "Invalid resolve data"))

    return {
        "ticket_id": row["id"],
        "status": row["status"],
        "resolved_by_agent_id": row["resolved_by_agent_id"],
        "fixed_at": row["fixed_at"].isoformat(),
    }


@mcp.tool()
async def mark_duplicate(
    ticket_id: int,
    duplicate_of: int,
    agent_id: int,
    note: str | None = None,
    ) -> dict:
    # Docstring written by an AI assistant (Claude).
    """Close a ticket as a duplicate of another ticket that reports the same bug.

    ticket_id is the copy that gets closed; duplicate_of is the original that
    stays open. Use this when file_ticket returned possible_duplicates and you
    agree they are the same bug, or when you spot a duplicate yourself. You
    don't need to claim either ticket first.

    If duplicate_of is itself a duplicate, the ticket is linked to that
    ticket's original instead, so duplicates always point at the original.

    Args:
        ticket_id: The duplicate ticket to close. Must be "open" or
            "in_progress".
        duplicate_of: The original ticket it duplicates.
        agent_id: Your agent id. The agent must exist and be active.
        note: Optional short reason why they are the same bug. It is saved
            in the ticket's history.

    Returns:
        {"ticket_id": int, "status": "duplicate", "duplicate_of": int}

    Raises:
        ValueError: If the agent doesn't exist or is inactive, either ticket
            doesn't exist, the ticket is already closed, or both ids point at
            the same ticket.
    """
    pool = db.get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                is_active = await conn.fetchval("SELECT is_active FROM agents WHERE id = $1", agent_id)
                if is_active is None:
                    raise ValueError(f"No agent with id {agent_id}")
                if not is_active:
                    raise ValueError(f"Agent with id {agent_id} is not active and cannot mark duplicated tickets")

                target = await conn.fetchrow("SELECT status, duplicate_of FROM tickets WHERE id = $1", duplicate_of)
                if target is None:
                    raise ValueError(f"No ticket with id {duplicate_of}")
                if target["status"] == "duplicate":
                    duplicate_of = target["duplicate_of"]

                row = await conn.fetchrow(
                    """
                    UPDATE tickets
                    SET status = 'duplicate', duplicate_of = $2
                    WHERE id = $1 AND status IN ('open','in_progress')
                    RETURNING id, status, duplicate_of
                    """,
                    ticket_id, duplicate_of,
                )

                if row is None:
                    status = await conn.fetchval("SELECT status FROM tickets WHERE id = $1", ticket_id)
                    if status is None:
                        raise ValueError(f"No ticket with id {ticket_id}")
                    raise ValueError(f"Ticket {ticket_id} is {status} and cannot be marked as a duplicate")

                await conn.execute(
                    """
                    UPDATE similarity_matches
                    SET outcome = 'confirmed'
                    WHERE (ticket_id = $1 AND matched_ticket_id = $2)
                       OR (ticket_id = $2 AND matched_ticket_id = $1)
                    """,
                    ticket_id, duplicate_of,
                )

                await conn.execute(
                    """
                    INSERT INTO ticket_events (ticket_id, agent_id, event_type, content)
                    VALUES ($1, $2, 'marked_duplicate', $3)
                    """,
                    ticket_id, agent_id, note,
                )
    except asyncpg.ForeignKeyViolationError:
        raise ValueError("Referenced agent or ticket no longer exists")
    except asyncpg.CheckViolationError as e:
        raise ValueError(CHECK_MESSAGES.get(e.constraint_name, "Invalid duplicate data"))

    return {
        "ticket_id": row["id"],
        "status": row["status"],
        "duplicate_of": row["duplicate_of"],
    }


@mcp.tool()
async def verify_ticket(ticket_id: int, agent_id: int, passed: bool, note: str | None = None) ->  dict:
    # Docstring written by an AI assistant (Claude).
    """Check another agent's fix and either confirm it or reopen the ticket.

    Only tickets with status "fixed" can be verified, and you cannot verify a
    ticket you resolved yourself; a different agent must check the fix.

    If the fix works, pass passed=True and the ticket becomes "verified".
    If it doesn't, pass passed=False with a note saying what is still broken;
    the ticket goes back to "open" with its claim and fix cleared, so any
    agent can claim it again. The previous fix stays in the ticket's history.

    Args:
        ticket_id: The id of the fixed ticket to check.
        agent_id: Your agent id. Must be active and not the agent that
            resolved the ticket.
        passed: True if the bug is gone, False if it still happens.
        note: What you checked and what you saw. Required when passed is
            False.

    Returns:
        If passed: {"ticket_id": int, "status": "verified",
                    "verified_at": ISO 8601 timestamp}
        If not:    {"ticket_id": int, "status": "open"}

    Raises:
        ValueError: If the agent doesn't exist or is inactive, the ticket
            doesn't exist or isn't "fixed", you resolved the ticket yourself,
            or passed is False without a note.
    """
    pool = db.get_pool()

    if not passed and not (note and note.strip()):
        raise ValueError("note is required when verification fails: say what is still broken")

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                is_active = await conn.fetchval("SELECT is_active FROM agents WHERE id = $1", agent_id)
                if is_active is None:
                    raise ValueError(f"No agent with id {agent_id}")
                if not is_active:
                    raise ValueError(f"Agent with id {agent_id} is not active and cannot verify tickets")

                
                if passed:
                    row = await conn.fetchrow(
                        """
                        UPDATE tickets
                        SET status = 'verified', verified_by_agent_id = $2, verified_at = NOW()
                        WHERE id = $1 AND status = 'fixed' AND resolved_by_agent_id <> $2
                        RETURNING id, status, verified_at
                        """,
                        ticket_id, agent_id,
                    )

                else:
                    row = await conn.fetchrow(
                        """
                        UPDATE tickets
                        SET status = 'open',
                            claimed_by_agent_id = NULL, claimed_at = NULL,
                            resolved_by_agent_id = NULL, fix_description = NULL, fixed_at = NULL
                        WHERE id = $1 AND status = 'fixed' AND resolved_by_agent_id <> $2
                        RETURNING id, status
                    
                        """,
                        ticket_id, agent_id,
                    )

                if row is  None:
                    info = await conn.fetchrow("SELECT status, resolved_by_agent_id FROM tickets WHERE id = $1", ticket_id)
                    if info is None:
                        raise ValueError (f"No ticket with id {ticket_id}")
                    if info["status"] != "fixed":
                        raise ValueError (f"Ticket {ticket_id} is {info['status']}; only fixed tickets can be verified")
                    raise ValueError (f"You resolved ticket {ticket_id}; another agent must verify it")
                
                await conn.execute(
                    """
                    INSERT INTO ticket_events (ticket_id, agent_id, event_type, content)
                    VALUES ($1, $2, $3, $4)
                    """,
                    ticket_id, agent_id, "verified" if passed else "reopened", note,
                )
    except asyncpg.ForeignKeyViolationError:
        raise ValueError("Referenced agent or ticket no longer exists")
    except asyncpg.CheckViolationError as e:
        raise ValueError(CHECK_MESSAGES.get(e.constraint_name, "Invalid verification data"))

    result = {"ticket_id": row["id"], "status": row["status"]}
    if passed:
        result["verified_at"] = row["verified_at"].isoformat()
    return result


@mcp.tool()  
async def unclaim_ticket(ticket_id: int, agent_id: int, note: str) -> dict:
    # Docstring written by an AI assistant (Claude).
    """Give up a ticket you claimed so another agent can work on it.

    Use this when you can't finish a fix: you're stuck, it's outside what you
    can change, or you need to stop. The ticket goes back to "open" with no
    claim. Only the agent that claimed the ticket can release it.

    Args:
        ticket_id: The id of the ticket to release. Must be "in_progress"
            and claimed by you.
        agent_id: Your agent id.
        note: What you tried, what you found, and why you're stopping, so the
            next agent doesn't start from zero. Must not be blank.

    Returns:
        {"ticket_id": int, "status": "open"}

    Raises:
        ValueError: If the agent doesn't exist, the ticket doesn't exist, is
            not in progress, or is claimed by another agent, or if note is
            blank.
    """
    pool = db.get_pool()

    if not note.strip():
        raise ValueError("note is required: say what you tried and why you're releasing the ticket")

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                is_active = await conn.fetchval("SELECT is_active FROM agents WHERE id = $1", agent_id)
                if is_active is None:
                    raise ValueError(f"No agent with id {agent_id}")
                
                row = await conn.fetchrow(
                    """
                    UPDATE tickets
                    SET status = 'open', claimed_by_agent_id = NULL, claimed_at = NULL
                    WHERE id = $1 AND status = 'in_progress' AND claimed_by_agent_id = $2
                    RETURNING id, status
                    """,

                    ticket_id, agent_id,
                )

                if row is None:
                    info = await conn.fetchrow(
                        "SELECT status, claimed_by_agent_id FROM tickets WHERE id = $1", ticket_id
                    )
                    if info is None:
                        raise ValueError(f"No ticket with id {ticket_id}")
                    if info["status"] != "in_progress":
                        raise ValueError(
                            f"Ticket {ticket_id} is {info['status']}; only in_progress tickets can be unclaimed"
                        )
                    raise ValueError(
                        f"Ticket {ticket_id} is claimed by agent {info['claimed_by_agent_id']}, not you"
                    )
                
                await conn.execute(
                        """
                        INSERT INTO ticket_events (ticket_id, agent_id, event_type, content)
                        VALUES ($1, $2, 'unclaimed', $3)
                        """,
                        ticket_id, agent_id, note,
                    )

    except asyncpg.ForeignKeyViolationError:
        raise ValueError("Referenced agent or ticket no longer exists")
    except asyncpg.CheckViolationError as e:
        raise ValueError(CHECK_MESSAGES.get(e.constraint_name, "Invalid unclaim data"))

    return {"ticket_id": row["id"], "status": row["status"]}


@mcp.tool()
async def list_tickets(
    status: Literal["open", "in_progress", "fixed", "wont_fix", "cannot_reproduce", 
                    "duplicate", "verified"] | None = "open",
    urgency: Literal["low","normal","high","critical"] | None = None,
    bug_type: Literal["bug","crash","regression","test_failure",
                     "build_failure", "performance", "security"] | None = None,
    repo: str | None = None,
    file_path: str | None = None,
    claimed_by_agent_id: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    # Docstring written by an AI assistant (Claude).
    """List tickets matching the given filters, most urgent first.

    Use this to find work to pick up, to check for known bugs in the repo or
    file you're working on before filing a new ticket, or to find tickets you
    have claimed. Results are short summaries; call get_ticket for a ticket's
    full description and history.

    All filters are optional and combined with AND. Tickets are sorted by
    urgency (critical, high, normal, low), then oldest first.

    Args:
        status: Only tickets with this status. Defaults to "open". Pass null
            to list tickets of every status.
        urgency: Only tickets with this urgency.
        bug_type: Only tickets of this kind.
        repo: Only tickets in this repository.
        file_path: Only tickets pointing at this exact file path.
        claimed_by_agent_id: Only tickets claimed by this agent. Pass your
            own id to find tickets you're working on.
        limit: Maximum number of tickets to return, 1 to 100. Default 20.
        offset: Number of tickets to skip, for paging. Default 0.

    Returns:
        {"tickets": [{"id", "title", "status", "urgency", "bug_type", "repo",
                      "file_path", "claimed_by_agent_id",
                      "created_at"}, ...],
         "count": number of tickets in this page}

    Raises:
        ValueError: If limit is below 1 or offset is negative.
    """

    return await queries.list_tickets(
        status=status, urgency=urgency, bug_type=bug_type, repo=repo,
        file_path=file_path, claimed_by_agent_id=claimed_by_agent_id,
        limit=limit, offset=offset,
    )



@mcp.tool()
async def get_ticket(ticket_id: int) -> dict:
    # Docstring written by an AI assistant (Claude).
    """Get one ticket's full details and its complete history.

    Use this before claiming a ticket, to read how to reproduce the bug and
    where it is; when picking up a reopened or released ticket, to read why
    the last fix failed or what the previous agent tried; when verifying, to
    read what the fix changed; and before mark_duplicate, to compare two
    tickets' descriptions instead of trusting the similarity score alone.

    Args:
        ticket_id: The id of the ticket.

    Returns:
        {"ticket": {"id", "title", "description", "status", "urgency",
                    "bug_type", "filed_by_agent_id", "claimed_by_agent_id",
                    "claimed_at", "resolved_by_agent_id", "fix_description",
                    "fixed_at", "verified_by_agent_id", "verified_at",
                    "duplicate_of", "repo", "commit_hash", "file_path",
                    "line_start", "line_end", "created_at"},
         "events": [{"event_type", "agent_id", "content", "created_at"}, ...]}

        Timestamps are ISO 8601 strings; fields that haven't happened yet
        (e.g. fixed_at on an open ticket) are null. Events are oldest first:
        filed, claimed, unclaimed, resolved, reopened, verified,
        marked_duplicate. Their content holds the notes and fix descriptions.

    Raises:
        ValueError: If the ticket doesn't exist.
    """

    return await queries.get_ticket(ticket_id)


            





