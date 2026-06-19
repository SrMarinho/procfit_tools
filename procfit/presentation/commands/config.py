"""Comando `config set / show` — gerencia credenciais no Credential Manager."""
from __future__ import annotations

from typing import Annotated, Optional

import keyring
import typer
from rich.table import Table

from procfit.infrastructure.config import DbConfig, _SERVICE as _KR_SERVICE
from procfit.presentation.rendering import console, err_console

config_app = typer.Typer(help="Gerencia a configuração de conexão.", rich_markup_mode="rich")

_FIELDS = [
    ("host",                "Host SQL Server",              "localhost"),
    ("port",                "Porta",                        "1433"),
    ("database_dados",      "Banco de dados (dados)",       "PBS_NAZARIA_DADOS_DEVELOPER"),
    ("database_dicionario", "Banco de dados (dicionário)",  "PBS_NAZARIA_DICIONARIO_DEVELOPER"),
    ("user",                "Usuário",                      ""),
    ("driver",              "Driver ODBC",                  "ODBC Driver 17 for SQL Server"),
]


@config_app.command("set")
def config_set(
    host: Annotated[Optional[str], typer.Option(help="Host SQL Server")] = None,
    port: Annotated[Optional[str], typer.Option(help="Porta")] = None,
    database_dados: Annotated[Optional[str], typer.Option(help="Banco de dados (dados)")] = None,
    database_dicionario: Annotated[Optional[str], typer.Option(help="Banco de dados (dicionário)")] = None,
    user: Annotated[Optional[str], typer.Option(help="Usuário SQL Server")] = None,
    driver: Annotated[Optional[str], typer.Option(help="Driver ODBC")] = None,
) -> None:
    """Salva a configuração no **Windows Credential Manager**."""
    vals = dict(
        host=host, port=port, database_dados=database_dados,
        database_dicionario=database_dicionario, user=user, driver=driver,
    )
    for key, label, default in _FIELDS:
        val = vals.get(key)
        if val is None:
            current = keyring.get_password(_KR_SERVICE, key) or default
            val = typer.prompt(label, default=current)
        if key == "port":
            try:
                int(val)
            except (ValueError, TypeError):
                err_console.print(f"[bold red]✖ Porta inválida:[/] '{val}' — use um número (ex: 1433).")
                raise typer.Exit(1)
        keyring.set_password(_KR_SERVICE, key, val)

    password = typer.prompt("Senha SQL Server", hide_input=True, confirmation_prompt=True)
    keyring.set_password(_KR_SERVICE, "password", password)
    console.print("[bold green]✔[/] Configuração salva no Windows Credential Manager.")


@config_app.command("show")
def config_show() -> None:
    """Exibe a configuração atual (senha mascarada)."""
    cfg = DbConfig.load()
    t = Table(title="Configuração Procfit", header_style="bold cyan")
    t.add_column("Campo", style="dim")
    t.add_column("Valor")
    t.add_row("Host",             cfg.host)
    t.add_row("Porta",            str(cfg.port))
    t.add_row("Banco dados",      cfg.database_dados)
    t.add_row("Banco dicionário", cfg.database_dicionario)
    t.add_row("Usuário",          cfg.user)
    t.add_row("Senha",            "***" if cfg.password else "[dim](não definida)[/]")
    t.add_row("Driver",           cfg.driver)
    console.print(t)
    fonte = "[dim]Fonte: Windows Credential Manager[/]" \
        if keyring.get_password(_KR_SERVICE, "host") else \
        "[dim]Fonte: variável de ambiente / .env[/]"
    console.print(fonte)
