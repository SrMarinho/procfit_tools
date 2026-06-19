"""Comando `health` — verifica conectividade com os dois bancos."""
from __future__ import annotations

import time

import connectorx as cx
import typer
from rich.table import Table

from procfit.infrastructure.config import DbConfig
from procfit.presentation.container import init_logging
from procfit.presentation.rendering import console


def register(app: typer.Typer) -> None:
    app.command("health")(cmd_health)


def cmd_health() -> None:
    """Verifica a conexão com os dois bancos SQL Server."""
    init_logging()
    cfg = DbConfig.load()

    results: list[tuple[str, str, str | None]] = []
    for label, conn in (("dados", cfg.conn_dados), ("dicionario", cfg.conn_dicionario)):
        t0 = time.perf_counter()
        try:
            cx.read_sql(conn, "SELECT 1 AS ok", return_type="arrow")
            elapsed = round((time.perf_counter() - t0) * 1000)
            results.append((label, "ok", f"{elapsed}ms"))
        except Exception as e:
            results.append((label, "fail", str(e)))

    t = Table(header_style="bold cyan")
    t.add_column("Banco")
    t.add_column("Status")
    t.add_column("Detalhe")
    for label, status, detail in results:
        if status == "ok":
            t.add_row(label, "[bold green]✔ ok[/]", detail or "")
        else:
            t.add_row(label, "[bold red]✖ falha[/]", detail or "")
    console.print(t)

    if any(s == "fail" for _, s, _ in results):
        raise typer.Exit(1)
