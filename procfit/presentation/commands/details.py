"""Comando `show` — detalha uma consulta (descrição, SQL, parâmetros)."""
from __future__ import annotations

from typing import Annotated

import typer
from rich.syntax import Syntax
from rich.table import Table

from procfit.presentation.concurrency import TimeoutError_, call_with_timeout
from procfit.presentation.container import Components, init_logging
from procfit.presentation.rendering import console, err_console


def register(app: typer.Typer) -> None:
    app.command("show")(cmd_show)


def cmd_show(
    consulta: Annotated[str, typer.Argument(help="Nome da consulta")],
    mostrar_sql: Annotated[bool, typer.Option("-s", "--sql", help="Exibe o SQL formatado")] = False,
    raw: Annotated[bool, typer.Option("--raw", help="Imprime só o SQL cru (pipeable)")] = False,
) -> None:
    """Mostra detalhes de uma consulta: descrição e parâmetros esperados.

    Por padrão o SQL não é exibido. Use [cyan]-s[/] para vê-lo formatado,
    ou [cyan]--raw[/] para imprimir só o SQL cru (pipeable).
    """
    init_logging()
    show_uc = Components().descrever_uc()
    try:
        detalhe = call_with_timeout(lambda: show_uc.execute(consulta), timeout=10)
    except (TimeoutError_, Exception) as e:
        err_console.print(f"[bold red]✖ Erro de conexão:[/] {e}")
        raise typer.Exit(1)

    if detalhe is None:
        err_console.print(f"[bold red]✖ Consulta '{consulta}' não encontrada.[/]")
        raise typer.Exit(1)

    if raw:
        print(detalhe.sql.strip())
        return

    console.print(f"\n[bold]Consulta:[/] [cyan]{detalhe.nome}[/]")
    if detalhe.descricao:
        console.print(f"[bold]Descrição:[/] {detalhe.descricao}")
    if mostrar_sql and detalhe.sql:
        console.print("[bold]SQL:[/]")
        console.print(Syntax(detalhe.sql.strip(), "sql", theme="ansi_dark", word_wrap=True))

    if not detalhe.parametros:
        console.print("\n[dim](sem parâmetros)[/]")
        return

    table = Table(
        title=f"Parâmetros ({len(detalhe.parametros)})",
        header_style="bold cyan",
        title_justify="left",
    )
    table.add_column("Ordem", justify="right")
    table.add_column("Flag", style="cyan")
    table.add_column("Obrig.", justify="center")
    table.add_column("Título")
    table.add_column("Lookup", style="magenta")
    for p in detalhe.parametros:
        req = "[green]sim[/]" if p.obrigatorio else "[dim]não[/]"
        table.add_row(str(p.ordem), f"--{p.flag}", req, p.titulo, p.lookup or "—")
    console.print(table)
    console.print(f"\n[dim]Dica: procfit run {detalhe.nome} --help[/]")
