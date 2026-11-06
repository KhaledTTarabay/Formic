import typer
from formic.cli import tickets

app = typer.Typer(help="Formic CLI: see what your agents are doing right now.", no_args_is_help=True)
app.add_typer(tickets.app, name="tickets", help="Browse tickets.")