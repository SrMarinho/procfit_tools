"""Raiz da aplicação: monta o app Typer, registra comandos e expõe `main`.

O comando `run` é Click puro (parâmetros dinâmicos), injetado no grupo Typer
via typer.main.get_command().
"""
from __future__ import annotations

import sys

import typer
from typer.main import get_command

from procfit.presentation.commands import details, health, listing
from procfit.presentation.commands.config import config_app
from procfit.presentation.commands.run import build_run_command

app = typer.Typer(
    name="procfit",
    help="CLI para executar consultas do Procfit ERP direto no SQL Server.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
)
app.add_typer(config_app, name="config")
health.register(app)
listing.register(app)
details.register(app)


def _reconfigure_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", newline="")
            except Exception:
                pass


def main() -> None:
    """Entry point do CLI."""
    _reconfigure_streams()
    click_app = get_command(app)
    click_app.add_command(build_run_command(), "run")  # type: ignore[union-attr]
    try:
        click_app()
    except Exception as e:
        if type(e).__name__ in ("Exit", "Abort"):
            code = getattr(e, "code", None)
            if code is None:
                code = e.args[0] if e.args and isinstance(e.args[0], int) else 0
            sys.exit(code)
        raise
