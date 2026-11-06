import typer
from typing import Annotated
from rich.console import Console
from rich.table import Table
from formic.cli import client

app = typer.Typer(help="Browse tickets.", no_args_is_help=True)
console = Console()

URGENCY_STYLE = {"critical": "bold_red", "high": "red", "medium": "yellow", "low": "dim"}


@app.command("list")
def list_tickets(
    status: Annotated[str, typer.Option(help="open, in_progress, fixed, ...")] = "open",
    urgency: Annotated[str | None, typer.Option()] = None,
    bug_type: Annotated[str | None, typer.Option("--type")] = None,
    repo: Annotated[str | None, typer.Option()] = None,
    file: Annotated[str | None, typer.Option(help="Exact file path")] = None,
    agent: Annotated[int | None, typer.Option(help="Only tickets claimed by this agent id")] = None,
    limit: Annotated[int, typer.Option()] = 20,
):
    """List tickets, with urgent first."""
    data = client.get(
        "/tickets",
        status=status,
        urgency=urgency,
        bug_type=bug_type,
        repo=repo,
        file=file,
        agent=agent,
        limit=limit,
    )
    if not data["tickets"]:
        console.print("No tickets found.")
        return
    
    table = Table("ID", "Urgency", "Status", "Title", "Repo", "File", "Agent")
    for t in data["tickets"]:
        style = URGENCY_STYLE[t["urgency"]]
        table.add_row(
            str(t["id"]),
            f"[{style}]{t['urgency']}[/]" if style else t["urgency"],
            t["status"],
            t["title"],
            t["repo"] or "",
            t["file_path"] or "",
            str(t["claimed_by_agent_id"] or ""),
        )
    console.print(table)


@app.command("show")
def show_ticket(ticket_id: int):
    """Show details of a ticket."""
    data = client.get(f"/tickets/{ticket_id}")
    t = data["ticket"]

    console.print(f"[bold]#{t['id']}[/] {t['title']}")
    console.print(f"{t['status']} · {t['urgency']} · {t['bug_type']}")
    if t["file_path"]:
        lines = f":{t['line_start']}-{t['line_end']}" if t["line_start"] else ""
        console.print(f"{t['repo'] or ''} {t['file_path']}{lines}".strip())
    console.print()
    console.print(t["description"])
    if t["fix_description"]:
        console.print(f"\n[bold]Fix:[/] {t['fix_description']}")

    console.print("\n[bold]History[/]")
    for e in data["events"]:
        when = e["created_at"][:16].replace("T", " ")
        who = f"agent {e['agent_id']}" if e["agent_id"] else ""
        console.print(f"  {when}  {e['event_type']:<17} {who:<9} {e['content'] or ''}")

