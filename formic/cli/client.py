import os 
import httpx
import typer

FORMIC_URL = os.environ.get("FORMIC_URL", "http://localhost:8000")
FORMIC_URL = FORMIC_URL.rstrip("/")


def get(path: str, **params) -> dict:
    """GET an API path and return the JSON, or exit with a readable error."""
    params = {key: value for key, value in params.items() if value is not None}
    try:
        response = httpx.get(f"{FORMIC_URL}/api{path}", params=params, timeout=10)
    except httpx.ConnectError:
        typer.secho(f"Error: Could not connect to Formic at {FORMIC_URL}. Is the server running?", fg="red", err=True)
        raise typer.Exit(1)
    except httpx.RequestError:
        typer.secho(f"Error: Request to Formic at {FORMIC_URL} failed.", fg="red", err=True)
        raise typer.Exit(1)

    if response.status_code >= 400:
        typer.secho(f"Error {response.status_code}: {_detail(response)}", fg="red", err=True)
        raise typer.Exit(1)
    return response.json()


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError:
        return response.text
    if isinstance(detail, list):
        return "; ".join(f"{'.'.join(map(str, d['loc'][1:]))}: {d['msg']}" for d in detail)
    if detail is None:
        return response.text
    return str(detail)