"""Interface de linha de comando (CLI) do procfit.

Padrões:
- Command: cada comando (list, show, run) é um Click Command
- Dynamic Command (RunCommand): subclasse de click.Command que injeta
  dinamicamente as opções vindas do banco CONSULTAS_PARAMS, com proteção
  de timeout para evitar travamento se o banco estiver offline
- Factory / DI manual: o wiring das dependências é feito no setup_app()

A CLI usa Click (base do Typer) diretamente para o comando `run` porque
precisamos de acesso completo ao mecanismo de parse de argumentos para
injetar opções dinamicamente. Os comandos `list` e `show` usam @click.command
normal.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

import click
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table

from src.application.use_cases import (
    DescreverConsultaUseCase,
    ExecutarConsultaUseCase,
    ListarConsultasUseCase,
)
from src.domain.enums import ExportFormato
from src.infrastructure.config import DbConfig, ExportConfig
from src.infrastructure.database import (
    ConnectorXExecutor,
    SqlServerParamRepo,
    SqlServerQueryRepo,
)
from src.infrastructure.exporters import CsvExporter, XlsxExporter

logger = logging.getLogger(__name__)

console = Console()
err_console = Console(stderr=True)


def _human_size(n: int) -> str:
    """Formata bytes em B/KB/MB/GB."""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


# ═══════════════════════════════════════════════════════════════════
# Helpers: Timeout para chamadas ao banco
# ═══════════════════════════════════════════════════════════════════

class TimeoutError_(Exception):
    """A chamada ao banco excedeu o tempo limite."""

T = TypeVar("T")

def _call_with_timeout(func: Callable[[], T], timeout: int = 15) -> T:
    """
    Executa uma função em thread separada com timeout.

    Retorna o valor da função ou levanta TimeoutError_ se exceder o timeout.
    Útil para chamadas ao banco (connectorx não tem timeout nativo).
    """
    result: list[T] = []
    exception: list[Exception] = []

    def _run() -> None:
        try:
            result.append(func())
        except Exception as e:
            exception.append(e)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        raise TimeoutError_(f"Timeout de {timeout}s excedido")

    if exception:
        raise exception[0]

    return result[0]


def _run_interruptible(func: Callable[[], T]) -> T:
    """Executa func em thread daemon, deixando o main thread livre para Ctrl+C.

    connectorx é Rust e segura a GIL durante o fetch, bloqueando o
    KeyboardInterrupt. Rodando em daemon e fazendo join em fatias curtas, o
    Ctrl+C é entregue imediatamente; a thread daemon morre junto com o processo.
    """
    result: list[T] = []
    exception: list[BaseException] = []

    def _run() -> None:
        try:
            result.append(func())
        except BaseException as e:  # noqa: BLE001
            exception.append(e)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    while thread.is_alive():
        thread.join(timeout=0.1)

    if exception:
        raise exception[0]
    return result[0]


# ═══════════════════════════════════════════════════════════════════
# Wiring / Injeção de Dependência
# ═══════════════════════════════════════════════════════════════════

def _setup_app() -> tuple[ListarConsultasUseCase, DescreverConsultaUseCase, ExecutarConsultaUseCase]:
    """
    Factory method: cria toda a árvore de dependências.
    Padrão: Simple Factory / DI Container manual.
    """
    db_cfg = DbConfig.from_env()
    export_cfg = ExportConfig()

    # Repositories
    query_repo = SqlServerQueryRepo(db_cfg)
    param_repo = SqlServerParamRepo(db_cfg)

    # Executor
    executor = ConnectorXExecutor(db_cfg)

    # Exporters (Strategy)
    exporters = {
        ExportFormato.CSV: CsvExporter(delimiter=export_cfg.csv_delimiter),
        ExportFormato.XLSX: XlsxExporter(sheet_name=export_cfg.xlsx_sheet_name),
    }

    # Use Cases
    list_uc = ListarConsultasUseCase(query_repo)
    show_uc = DescreverConsultaUseCase(query_repo, param_repo)
    run_uc = ExecutarConsultaUseCase(query_repo, param_repo, executor, exporters)

    return list_uc, show_uc, run_uc


# ═══════════════════════════════════════════════════════════════════
# CLI base
# ═══════════════════════════════════════════════════════════════════

@click.group(help="CLI para executar consultas do Procfit ERP direto no SQL Server.")
def cli() -> None:
    """Procfit CLI — consultas modernas sem precisar do desktop legado."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s | %(message)s",
    )


@cli.command("list", help="Lista as consultas (filtros opcionais com LIKE).")
@click.argument("filtro", required=False)
@click.option("-d", "--descricao", default=None, help="Filtro LIKE na descrição.")
def cmd_list(filtro: str | None, descricao: str | None) -> None:
    """Lista consultas (nome + descrição).

    FILTRO é um padrão LIKE do SQL Server (use % como curinga) aplicado ao
    NOME. Use -d/--descricao para filtrar pela DESCRIÇÃO. Os dois combinam
    com AND. Ex: 'B2B%', '%PAGAMENTO%', --descricao '%cliente%'.
    """
    list_uc, _, _ = _setup_app()
    try:
        consultas = _call_with_timeout(
            lambda: list_uc.execute(filtro, descricao), timeout=10
        )
    except (TimeoutError_, Exception) as e:
        err_console.print(f"[bold red]✖ Erro de conexão:[/] {e}")
        raise sys.exit(1)

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


@cli.command("show", help="Mostra detalhes de uma consulta e seus parâmetros.")
@click.argument("consulta")
@click.option("-s", "--sql", "mostrar_sql", is_flag=True, help="Exibe também o SQL (formatado).")
@click.option("--raw", is_flag=True, help="Imprime apenas o SQL cru (pipeable, sem mais nada).")
def cmd_show(consulta: str, mostrar_sql: bool, raw: bool) -> None:
    """Mostra parâmetros, flags e metadados de uma consulta.

    Por padrão o SQL não é exibido. Use -s/--sql para vê-lo formatado junto
    dos detalhes, ou --raw para imprimir só o SQL cru (pipeable).
    """
    _, show_uc, _ = _setup_app()
    try:
        detalhe = _call_with_timeout(lambda: show_uc.execute(consulta), timeout=10)
    except (TimeoutError_, Exception) as e:
        err_console.print(f"[bold red]✖ Erro de conexão:[/] {e}")
        raise sys.exit(1)

    if detalhe is None:
        err_console.print(f"[bold red]✖ Consulta '{consulta}' não encontrada.[/]")
        raise sys.exit(1)

    # --raw: só o SQL cru (sem cor/cabeçalho), pipeable via stdout.
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
    console.print(f"\n[dim]Dica: uv run main.py run {detalhe.nome} --help[/]")


# ═══════════════════════════════════════════════════════════════════
# Comando RUN com Parâmetros Dinâmicos
# ═══════════════════════════════════════════════════════════════════

class DynamicRunCommand(click.Command):
    """
    click.Command que injeta dinamicamente opções vindas do banco.

    Padrão: Template Method — herda click.Command e sobrescreve
    parse_args para injetar parâmetros antes do parse.

    A injeção roda em uma thread separada com timeout de 5s para
    evitar travamento caso o SQL Server não esteja acessível.
    """

    DB_TIMEOUT = 5  # segundos

    def __init__(
        self,
        *args: Any,
        param_repo: Optional[SqlServerParamRepo] = None,
        run_uc: Optional[ExecutarConsultaUseCase] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._param_repo = param_repo
        self._run_uc = run_uc
        self._param_cache: dict[str, bool] = {}

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        """
        Sobrescreve parse_args para injetar opções dinâmicas.

        Usa thread com timeout para a chamada ao banco.
        Se o banco não responder em DB_TIMEOUT segundos, segue sem
        parâmetros dinâmicos (mostra apenas as opções fixas).
        """
        consulta = self._extract_consulta(args)

        if consulta and self._param_repo and consulta not in self._param_cache:
            self._load_params_threaded(consulta)

        return super().parse_args(ctx, args)

    def _load_params_threaded(self, consulta: str) -> None:
        """Carrega parâmetros em thread separada com timeout."""
        assert self._param_repo is not None
        param_repo = self._param_repo
        result: list[Any] = []
        exception: list[Exception] = []

        def _fetch() -> None:
            try:
                result.extend(param_repo.listar_por_consulta(consulta))
            except Exception as e:
                exception.append(e)

        thread = threading.Thread(target=_fetch, daemon=True)
        thread.start()
        thread.join(timeout=self.DB_TIMEOUT)

        if thread.is_alive():
            logger.warning("Timeout ao carregar parâmetros do banco para '%s'", consulta)
            return

        if exception:
            logger.warning("Erro ao carregar parâmetros: %s", exception[0])
            return

        self._param_cache[consulta] = True
        for p in result:
            self._add_option(p)

    def _add_option(self, p: Any) -> None:
        """Adiciona um click.Option para o parâmetro, se já não existir."""
        opt_name = p.flag_name
        existing = {o.name for o in self.params if isinstance(o, click.Option)}

        if opt_name not in existing:
            opt = click.Option(
                param_decls=[f"--{opt_name}"],
                help=p.titulo or p.nome,
                default=None,
                type=str,
                required=False,
                expose_value=True,
            )
            self.params.append(opt)

    def invoke(self, ctx: click.Context) -> Any:
        """Executa o comando: extrai params dinâmicos e chama o use case."""
        consulta = ctx.params.get("consulta", "")
        if not consulta:
            err_console.print("[bold red]✖ Nome da consulta é obrigatório.[/]")
            raise sys.exit(1)

        formato_str = ctx.params.get("format", "csv")
        output_str: str | None = ctx.params.get("output")
        verbose = ctx.params.get("verbose", False)
        force = ctx.params.get("force", False)
        dry_run = ctx.params.get("dry_run", False)

        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)

        # Extrai parâmetros dinâmicos (tudo que NÃO é opção fixa)
        valores: dict[str, str] = {}
        for key, value in ctx.params.items():
            if key in ("consulta", "format", "output", "verbose", "force", "dry_run"):
                continue
            if value is not None:
                valores[key.upper()] = str(value)

        # --dry-run: gera o SQL final com os parâmetros, sem executar (pipeable).
        if dry_run:
            try:
                assert self._run_uc is not None
                sql = self._run_uc.gerar_sql(consulta, valores)
            except ValueError as e:
                err_console.print(f"[bold red]✖[/] {e}")
                raise sys.exit(2)
            print(sql)
            return

        try:
            formato = ExportFormato.from_str(formato_str)
        except ValueError as e:
            err_console.print(f"[bold red]✖[/] {e}")
            raise sys.exit(2)

        # Define output padrão se não especificado
        if not output_str:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            output_str = f"{consulta}_{timestamp}.{formato.extension}"
        output = Path(output_str)

        # Cria as pastas do output se não existirem
        if output.parent and not output.parent.exists():
            output.parent.mkdir(parents=True, exist_ok=True)

        # Proteção contra sobrescrita (spec 4.4)
        if output.exists() and not force:
            if not click.confirm(f"Arquivo '{output}' já existe. Sobrescrever?"):
                console.print("Cancelado.")
                raise sys.exit(0)

        try:
            assert self._run_uc is not None
            run_uc = self._run_uc
            with console.status(f"Executando [cyan]{consulta}[/]..."):
                resultado = _run_interruptible(
                    lambda: run_uc.execute(consulta, valores, formato, output)
                )
        except KeyboardInterrupt:
            err_console.print("\n[yellow]⚠ Cancelado pelo usuário.[/]")
            raise sys.exit(130)
        except ValueError as e:
            err_console.print(f"[bold red]✖[/] {e}")
            raise sys.exit(2)
        except OSError as e:
            err_console.print(f"[bold red]✖ Erro ao escrever arquivo:[/] {e}")
            logger.exception("Falha na escrita")
            raise sys.exit(4)
        except Exception as e:
            err_console.print(f"[bold red]✖ Erro na execução:[/] {e}")
            logger.exception("Falha na execução")
            raise sys.exit(3)

        console.print(f"[bold green]✔ Concluído![/] {resultado.arquivo}")

        vazao = resultado.linhas / resultado.tempo_consulta if resultado.tempo_consulta else 0
        metricas = Table(show_header=False, box=None, pad_edge=False)
        metricas.add_column(style="dim")
        metricas.add_column(style="bold")
        metricas.add_row("Linhas", f"{resultado.linhas:,}".replace(",", "."))
        metricas.add_row("Colunas", str(resultado.colunas))
        metricas.add_row("Tempo consulta", f"{resultado.tempo_consulta}s")
        metricas.add_row("Tempo exportação", f"{resultado.tempo_export}s")
        metricas.add_row("Tempo total", f"{resultado.tempo_segundos}s")
        metricas.add_row("Tamanho", _human_size(resultado.tamanho_bytes))
        metricas.add_row("Vazão", f"{vazao:,.0f} linhas/s".replace(",", "."))
        console.print(metricas)

    @staticmethod
    def _extract_consulta(args: list[str]) -> Optional[str]:
        """Extrai o nome da consulta dos argumentos (primeiro não-opção)."""
        for arg in args:
            if not arg.startswith("-"):
                return arg
        return None


# Registra o comando `run` manualmente com a classe customizada
def _make_run_command() -> click.Command:
    """Factory: cria o comando run com DynamicRunCommand."""
    db_cfg = DbConfig.from_env()
    export_cfg = ExportConfig()

    query_repo = SqlServerQueryRepo(db_cfg)
    param_repo = SqlServerParamRepo(db_cfg)
    executor = ConnectorXExecutor(db_cfg)

    exporters = {
        ExportFormato.CSV: CsvExporter(delimiter=export_cfg.csv_delimiter),
        ExportFormato.XLSX: XlsxExporter(sheet_name=export_cfg.xlsx_sheet_name),
    }

    run_uc = ExecutarConsultaUseCase(query_repo, param_repo, executor, exporters)

    cmd = DynamicRunCommand(
        name="run",
        param_repo=param_repo,
        run_uc=run_uc,
        params=[
            click.Argument(["consulta"], required=True),
            click.Option(
                ["--format", "-f"],
                default="csv",
                show_default=True,
                type=click.Choice(["csv", "xlsx"]),
                help="Formato de exportação",
            ),
            click.Option(
                ["--output", "-o"],
                default=None,
                type=click.Path(),
                help="Arquivo de saída (default: <consulta>_<timestamp>.<ext>)",
            ),
            click.Option(
                ["--verbose", "-v"],
                is_flag=True,
                help="Modo verboso com logs de debug",
            ),
            click.Option(
                ["--force"],
                is_flag=True,
                help="Sobrescreve o arquivo de saída sem perguntar",
            ),
            click.Option(
                ["--dry-run"],
                is_flag=True,
                help="Gera o SQL com os parâmetros substituídos (não executa).",
            ),
        ],
        help="Executa uma consulta e exporta o resultado.\n\n"
        "Os parâmetros específicos da consulta são carregados do banco "
        "e aparecem automaticamente. Se o banco não estiver acessível, "
        "apenas as opções fixas são mostradas.\n\n"
        "Dica: use 'uv run main.py show CONSULTA' para ver os parâmetros esperados.",
        epilog="Exemplo: uv run main.py run OL_APURACOES_MARCAS --data-ini 2024-01-01 --data-fim 2024-12-31 -f xlsx",
    )
    return cmd


cli.add_command(_make_run_command(), "run")


def main() -> None:
    """Entry point do CLI."""
    # Força UTF-8 no console (Windows usa cp1252 por padrão e quebra com
    # acentos e box-drawing das tabelas/SQL).
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", newline="")
            except Exception:
                pass
    cli()


if __name__ == "__main__":
    main()