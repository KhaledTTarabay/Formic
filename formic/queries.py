from formic import db

async def list_tickets(status, urgency, bug_type, repo, file_path, claimed_by_agent_id, limit, offset) -> dict:
    conditions = []
    params = []

    def add(column, value):
        params.append(value)
        conditions.append(f"{column} = ${len(params)}")

    if status is not None:
        add("status", status)
    if urgency is not None:
        add("urgency", urgency)
    if bug_type is not None:
        add("bug_type", bug_type)
    if repo is not None:
        add("repo", repo)
    if file_path is not None:
        add("file_path", file_path)
    if claimed_by_agent_id is not None:
        add("claimed_by_agent_id", claimed_by_agent_id)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    params.append(min(limit, 100))
    params.append(offset)

    if limit < 1 or offset < 0:
        raise ValueError("limit must be at least 1 and offset cannot be negative")


    rows = await db.get_pool().fetch(
        f"""
        SELECT id, title, status, urgency, bug_type, repo, file_path,
                claimed_by_agent_id, created_at
        FROM tickets
        {where}
        ORDER BY array_position(ARRAY['critical','high','normal','low'], urgency), created_at
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
        """,
        *params,
    )

    tickets = [
        {**dict(r),"created_at": r["created_at"].isoformat()}
        for r in rows
    ]

    return {"tickets": tickets, "count": len(tickets)}


async def get_ticket(ticket_id) -> dict:
    pool = db.get_pool()

    ticket = await pool.fetchrow(
        """
        SELECT id, title, description, status, urgency, bug_type,
               filed_by_agent_id, claimed_by_agent_id, claimed_at,
               resolved_by_agent_id, fix_description, fixed_at,
               verified_by_agent_id, verified_at, duplicate_of,
               repo, commit_hash, file_path, line_start, line_end, created_at
        FROM tickets WHERE id = $1
        """,
        ticket_id,
    )
    if ticket is None:
        raise ValueError(f"No ticket with id {ticket_id}")
    
    events = await pool.fetch(
        "SELECT event_type, agent_id, content, created_at FROM ticket_events WHERE ticket_id = $1 ORDER BY id",
        ticket_id,
    )

    def iso(value):
        return value.isoformat() if value is not None else None

    ticket_data = dict(ticket)
    for key in ("claimed_at","fixed_at","verified_at", "created_at"):
        ticket_data[key] = iso(ticket_data[key])

    return {"ticket": ticket_data,
            "events": [{**dict(e), "created_at": iso(e["created_at"])} for e in events],
    }