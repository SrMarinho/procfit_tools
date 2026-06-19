"""Comando `list` — lista as consultas disponíveis."""
from __future__ import annotations

from typing import Annotated, Optional

import typer
from rich.table import Table

from procfit.presentation.concurrency import TimeoutError_, call_with_timeout
from procfit.presentation.container import Components, init_logging
from procfit.presentation.rendering import console, err_console


def register(app: typer.Typer) -> None:
    app.command("list")(cmd_list)


def cmd_list(
    filtro: Annotated[Optional[str], typer.Argument(help="Filtro LIKE no nome (ex: 'B2B%')")] = None,
    descricao: Annotated[Optional[str], typer.Option("-d", "--descricao", help="Filtro LIKE na descrição")] = None,
) -> None:
    """Lista as consultas disponíveis (nome + descrição).

    FILTRO é um padrão LIKE do SQL Server (use % como curinga) aplicado ao nome.
    Use [cyan]-d[/] para filtrar pela descrição. Os dois combinam com AND.
    """
    init_logging()
    list_uc = Components().listar_uc()
    try:
        consultas = call_with_timeout(
            lambda: list_uc.execute(filtro, descricao), timeout=10
        )
    except (TimeoutError_, Exception) as e:
        err_console.print(f"[bold red]✖ Erro de conexão:[/] {e}")
        raise typer.Exit(1)

    filtro_desc = " ".join(
        p for p in (
            f"nome~'{filtro}'" if filtro else "",
            f"descrição~'{descricao}'" if descricao else "",
        ) if p
    )
    if not consultas:
        msg = f"Nenhuma consulta encontrada ({filtro_desc})." if filtro_desc \
            else "Nenhuma consulta encontrada."
        console.print(msg)
        return

    titulo = f"Consultas Procfit ({filtro_desc})" if filtro_desc else "Consultas Procfit"
    table = Table(title=titulo, header_style="bold cyan")
    table.add_column("Consulta", style="cyan")
    table.add_column("Descrição")
    for c in consultas:
        table.add_row(c.nome, c.descricao or "—")
    console.print(table)
    console.print(f"Total: [bold]{len(consultas)}[/] consultas")
