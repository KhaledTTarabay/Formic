from fastapi import APIRouter, HTTPException
from formic import queries
from formic.formic_types import Status, Urgency, BugType

router = APIRouter()

@router.get("/tickets")
async def list_tickets(
    status: Status | None = "open",
    urgency: Urgency | None = None,
    bug_type: BugType | None = None,
    repo: str | None = None,
    file_path: str | None = None,
    claimed_by_agent_id: int | None = None,
    limit: int = 20,
    offset: int = 0,
):
    try:
        return await queries.list_tickets(
            status=status,
            urgency=urgency,
            bug_type=bug_type,
            repo=repo,
            file_path=file_path,
            claimed_by_agent_id=claimed_by_agent_id,
            limit=limit,
            offset=offset
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: int):
    try:
        return await queries.get_ticket(ticket_id=ticket_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))