"""Interface de linha de comando (CLI) do procfit.

Padrões:
- Typer para list / show / config (rich help automático).
- DynamicRunCommand (click.Command) para run: injeta flags do banco em parse_args.
  Adicionado ao grupo Typer via typer.main.get_command() em main().
- Factory / DI manual: wiring de dependências em _setup_app() / _make_run_command().
"""
from __future__ import annotations

import itertools
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Annotated, Any, Callable, Optional, TypeVar

import pyarrow as pa

import click
import keyring
import typer
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table
from typer.main import get_command

from procfit.application.use_cases import (
    DescreverConsultaUseCase,
    ExecutarConsultaUseCase,
    ListarConsultasUseCase,
)
from procfit.domain.enums import ExportFormato
from procfit.infrastructure.config import DbConfig, ExportConfig, _SERVICE as _KR_SERVICE
from procfit.infrastructure.database import (
    ConnectorXExecutor,
    SqlServerCampoRepo,
    SqlServerParamRepo,
    SqlServerQueryRepo,
)
from procfit.infrastructure.exporters import CsvExporter, XlsxExporter

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


_PREVIEW_LIMIT = 100


def _render_metricas(
    dest: Console,
    *,
    linhas: int,
    colunas: int,
    tempo_consulta: float,
    tempo_export: float | None = None,
    tempo_total: float | None = None,
    tamanho: int | None = None,
) -> None:
    vazao = linhas / tempo_consulta if tempo_consulta else 0
    t = Table(show_header=False, box=None, pad_edge=False)
    t.add_column(style="dim")
    t.add_column(style="bold")
    t.add_row("Linhas", f"{linhas:,}".replace(",", "."))
    t.add_row("Colunas", str(colunas))
    t.add_row("Tempo consulta", f"{round(tempo_consulta, 2)}s")
    if tempo_export is not None:
        t.add_row("Tempo exportação", f"{tempo_export}s")
    if tempo_total is not None:
        t.add_row("Tempo total", f"{tempo_total}s")
    if tamanho is not None:
        t.add_row("Tamanho", _human_size(tamanho))
    t.add_row("Vazão", f"{vazao:.0f} linhas/s")
    dest.print(t)


def _render_preview(table: Any, tempo_consulta: float) -> None:
    total = table.num_rows
    rich_t = Table(header_style="bold cyan")
    for col in table.column_names:
        rich_t.add_column(str(col))
    preview = table.slice(0, _PREVIEW_LIMIT)
    cols = [preview.column(i).to_pylist() for i in range(preview.num_columns)]
    for i in range(preview.num_rows):
        rich_t.add_row(*["" if cols[c][i] is None else str(cols[c][i]) for c in range(len(cols))])
    console.print(rich_t)
    if total > _PREVIEW_LIMIT:
        console.print(
            f"[dim]... e mais {total - _PREVIEW_LIMIT} linhas. "
            f"Use -o para exportar tudo.[/]"
        )
    _render_metricas(
        console, linhas=total, colunas=table.num_columns, tempo_consulta=tempo_consulta
    )


# ═══════════════════════════════════════════════════════════════════
# Helpers: Timeout / thread interruptível
# ═══════════════════════════════════════════════════════════════════

class TimeoutError_(Exception):
    pass

T = TypeVar("T")

def _call_with_timeout(func: Callable[[], T], timeout: int = 15) -> T:
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
    db_cfg = DbConfig.load()
    export_cfg = ExportConfig()
    query_repo = SqlServerQueryRepo(db_cfg)
    param_repo = SqlServerParamRepo(db_cfg)
    campo_repo = SqlServerCampoRepo(db_cfg)
    executor = ConnectorXExecutor(db_cfg)
    exporters = {
        ExportFormato.CSV: CsvExporter(delimiter=export_cfg.csv_delimiter),
        ExportFormato.XLSX: XlsxExporter(sheet_name=export_cfg.xlsx_sheet_name),
    }
    list_uc = ListarConsultasUseCase(query_repo)
    show_uc = DescreverConsultaUseCase(query_repo, param_repo)
    run_uc = ExecutarConsultaUseCase(query_repo, param_repo, executor, exporters, campo_repo)
    return list_uc, show_uc, run_uc


# ═══════════════════════════════════════════════════════════════════
# App Typer
# ═══════════════════════════════════════════════════════════════════

app = typer.Typer(
    name="procfit",
    help="CLI para executar consultas do Procfit ERP direto no SQL Server.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
)

config_app = typer.Typer(help="Gerencia a configuração de conexão.", rich_markup_mode="rich")
app.add_typer(config_app, name="config")


def _init_logging() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(message)s")


# ═══════════════════════════════════════════════════════════════════
# Comando: config set / show
# ═══════════════════════════════════════════════════════════════════

_CONFIG_FIELDS = [
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
    for key, label, default in _CONFIG_FIELDS:
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


# ═══════════════════════════════════════════════════════════════════
# Comando: health
# ═══════════════════════════════════════════════════════════════════

@app.command("health")
def cmd_health() -> None:
    """Verifica a conexão com os dois bancos SQL Server."""
    import time
    import connectorx as cx

    _init_logging()
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


# ═══════════════════════════════════════════════════════════════════
# Comando: list
# ═══════════════════════════════════════════════════════════════════

@app.command("list")
def cmd_list(
    filtro: Annotated[Optional[str], typer.Argument(help="Filtro LIKE no nome (ex: 'B2B%')")] = None,
    descricao: Annotated[Optional[str], typer.Option("-d", "--descricao", help="Filtro LIKE na descrição")] = None,
) -> None:
    """Lista as consultas disponíveis (nome + descrição).

    FILTRO é um padrão LIKE do SQL Server (use % como curinga) aplicado ao nome.
    Use [cyan]-d[/] para filtrar pela descrição. Os dois combinam com AND.
    """
    _init_logging()
    list_uc, _, _ = _setup_app()
    try:
        consultas = _call_with_timeout(
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


# ═══════════════════════════════════════════════════════════════════
# Comando: show
# ═══════════════════════════════════════════════════════════════════

@app.command("show")
def cmd_show(
    consulta: Annotated[str, typer.Argument(help="Nome da consulta")],
    mostrar_sql: Annotated[bool, typer.Option("-s", "--sql", help="Exibe o SQL formatado")] = False,
    raw: Annotated[bool, typer.Option("--raw", help="Imprime só o SQL cru (pipeable)")] = False,
) -> None:
    """Mostra detalhes de uma consulta: descrição e parâmetros esperados.

    Por padrão o SQL não é exibido. Use [cyan]-s[/] para vê-lo formatado,
    ou [cyan]--raw[/] para imprimir só o SQL cru (pipeable).
    """
    _init_logging()
    _, show_uc, _ = _setup_app()
    try:
        detalhe = _call_with_timeout(lambda: show_uc.execute(consulta), timeout=10)
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


# ═══════════════════════════════════════════════════════════════════
# Comando RUN com Parâmetros Dinâmicos (Click direto)
# ═══════════════════════════════════════════════════════════════════

class DynamicRunCommand(click.Command):
    """click.Command que injeta dinamicamente opções vindas do banco."""

    DB_TIMEOUT = 5

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
        consulta = self._extract_consulta(args)
        if consulta and self._param_repo and consulta not in self._param_cache:
            self._load_params_threaded(consulta)
        return super().parse_args(ctx, args)

    def _load_params_threaded(self, consulta: str) -> None:
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
        opt_name = p.flag_name
        existing = {o.name for o in self.params if isinstance(o, click.Option)}
        if opt_name not in existing:
            opt = click.Option(
                param_decls=[f"--{opt_name}"],
                help=p.titulo or p.nome,
                default=(),
                type=str,
                multiple=True,
                required=False,
                expose_value=True,
            )
            self.params.append(opt)

    def invoke(self, ctx: click.Context) -> Any:
        consulta = ctx.params.get("consulta", "")
        if not consulta:
            err_console.print("[bold red]✖ Nome da consulta é obrigatório.[/]")
            sys.exit(1)

        formato_str = ctx.params.get("format", "csv")
        output_str: str | None = ctx.params.get("output")
        verbose = ctx.params.get("verbose", False)
        force = ctx.params.get("force", False)
        dry_run = ctx.params.get("dry_run", False)
        stdout_flag = ctx.params.get("stdout", False)
        no_header = ctx.params.get("no_header", False)

        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)

        # Separa params fixos dos dinâmicos; detecta multi-valor
        fixas = ("consulta", "format", "output", "verbose", "force", "dry_run", "stdout", "no_header")
        valores_base: dict[str, str] = {}
        valores_multi: dict[str, list[str]] = {}
        for key, value in ctx.params.items():
            if key in fixas:
                continue
            if isinstance(value, tuple):
                if len(value) == 1:
                    valores_base[key.upper()] = value[0]
                elif len(value) > 1:
                    valores_multi[key.upper()] = list(value)
            elif value is not None:
                valores_base[key.upper()] = str(value)

        # Gera lista de valores: cartesian product dos params multi-valor
        if valores_multi:
            mk = list(valores_multi.keys())
            all_valores: list[dict[str, str]] = [
                {**valores_base, **dict(zip(mk, combo))}
                for combo in itertools.product(*[valores_multi[k] for k in mk])
            ]
        else:
            all_valores = [valores_base]

        assert self._run_uc is not None
        run_uc = self._run_uc

        # ── dry-run ──────────────────────────────────────────────────
        if dry_run:
            n = len(all_valores)
            for i, valores in enumerate(all_valores):
                if n > 1:
                    combo_desc = ", ".join(f"{k}={v}" for k, v in valores.items() if k in valores_multi)
                    print(f"-- [{i + 1}/{n}] {combo_desc}")
                try:
                    sql = run_uc.gerar_sql(consulta, valores)
                except ValueError as e:
                    err_console.print(f"[bold red]✖[/] {e}")
                    sys.exit(2)
                print(sql)
            return

        try:
            formato = ExportFormato.from_str(formato_str)
        except ValueError as e:
            err_console.print(f"[bold red]✖[/] {e}")
            sys.exit(2)

        try:
            descricao = run_uc.obter_descricao(consulta)
        except Exception:
            descricao = ""
        rotulo = f"[cyan]{consulta}[/]" + (f" — {descricao}" if descricao else "")

        # ── executa todas as combinações e concatena ──────────────────
        n = len(all_valores)

        def _run_all() -> tuple[pa.Table, float]:
            tables: list[pa.Table] = []
            total_t = 0.0
            for i, valores in enumerate(all_valores):
                label = f"Executando {rotulo} ({i + 1}/{n})..." if n > 1 else f"Executando {rotulo}..."
                with (err_console if stdout_flag else console).status(label):
                    t, elapsed = _run_interruptible(lambda v=valores: run_uc.executar_tabela(consulta, v))
                tables.append(t)
                total_t += elapsed
            return (pa.concat_tables(tables) if len(tables) > 1 else tables[0]), total_t

        try:
            table, t_consulta = _run_all()
        except KeyboardInterrupt:
            err_console.print("\n[yellow]⚠ Cancelado pelo usuário.[/]")
            sys.exit(130)
        except ValueError as e:
            err_console.print(f"[bold red]✖[/] {e}")
            sys.exit(2)
        except Exception as e:
            err_console.print(f"[bold red]✖ Erro na execução:[/] {e}")
            logger.exception("Falha na execução")
            sys.exit(3)

        export_cfg = ExportConfig()

        # ── stdout ────────────────────────────────────────────────────
        if stdout_flag:
            if formato is ExportFormato.XLSX:
                err_console.print("[bold red]✖ XLSX é binário; --stdout só suporta csv.[/]")
                sys.exit(2)
            exporter = CsvExporter(export_cfg.csv_delimiter)
            linhas = exporter.exportar_stream(table, sys.stdout, include_header=not no_header)
            _render_metricas(err_console, linhas=linhas, colunas=table.num_columns, tempo_consulta=t_consulta)
            return

        # ── arquivo ───────────────────────────────────────────────────
        if output_str:
            output = Path(output_str).expanduser()
            if output.parent and not output.parent.exists():
                output.parent.mkdir(parents=True, exist_ok=True)
            if output.exists() and not force:
                if not click.confirm(f"Arquivo '{output}' já existe. Sobrescrever?"):
                    console.print("Cancelado.")
                    sys.exit(0)
            try:
                t1 = time.perf_counter()
                if formato is ExportFormato.CSV:
                    exporter_csv = CsvExporter(export_cfg.csv_delimiter)
                    linhas = exporter_csv.exportar(table, output, include_header=not no_header)
                else:
                    from procfit.infrastructure.exporters import XlsxExporter as _Xlsx
                    exporter_xlsx = _Xlsx(export_cfg.xlsx_sheet_name)
                    linhas = exporter_xlsx.exportar(table, output)
                t_export = round(time.perf_counter() - t1, 2)
            except OSError as e:
                err_console.print(f"[bold red]✖ Erro ao escrever arquivo:[/] {e}")
                logger.exception("Falha na escrita")
                sys.exit(4)
            tamanho = output.stat().st_size if output.exists() else 0
            console.print(f"[bold green]✔ Concluído![/] {output}")
            _render_metricas(
                console, linhas=linhas, colunas=table.num_columns,
                tempo_consulta=t_consulta, tempo_export=t_export,
                tempo_total=round(t_consulta + t_export, 2), tamanho=tamanho,
            )
            return

        # ── preview ───────────────────────────────────────────────────
        _render_preview(table, t_consulta)

    @staticmethod
    def _extract_consulta(args: list[str]) -> Optional[str]:
        for arg in args:
            if not arg.startswith("-"):
                return arg
        return None


def _make_run_command() -> click.Command:
    db_cfg = DbConfig.load()
    export_cfg = ExportConfig()
    query_repo = SqlServerQueryRepo(db_cfg)
    param_repo = SqlServerParamRepo(db_cfg)
    campo_repo = SqlServerCampoRepo(db_cfg)
    executor = ConnectorXExecutor(db_cfg)
    exporters = {
        ExportFormato.CSV: CsvExporter(delimiter=export_cfg.csv_delimiter),
        ExportFormato.XLSX: XlsxExporter(sheet_name=export_cfg.xlsx_sheet_name),
    }
    run_uc = ExecutarConsultaUseCase(query_repo, param_repo, executor, exporters, campo_repo)

    return DynamicRunCommand(
        name="run",
        param_repo=param_repo,
        run_uc=run_uc,
        params=[
            click.Argument(["consulta"], required=True),
            click.Option(["--format", "-f"], default="csv", show_default=True,
                         type=click.Choice(["csv", "xlsx"]), help="Formato de exportação"),
            click.Option(["--output", "-o"], default=None, type=click.Path(),
                         help="Arquivo de saída. Sem -o, mostra tabela no terminal."),
            click.Option(["--stdout"], is_flag=True,
                         help="CSV cru no stdout (pipeable); métricas no stderr."),
            click.Option(["--verbose", "-v"], is_flag=True, help="Modo verboso"),
            click.Option(["--force"], is_flag=True, help="Sobrescreve sem perguntar"),
            click.Option(["--dry-run"], is_flag=True,
                         help="Gera o SQL parametrizado (não executa)."),
            click.Option(["--no-header"], is_flag=True,
                         help="Omite o cabeçalho no CSV (--stdout ou -o)."),
        ],
        help="Executa uma consulta e exporta o resultado.\n\n"
             "Os parâmetros da consulta são carregados automaticamente do banco.\n\n"
             "Dica: use 'procfit show CONSULTA' para ver os parâmetros esperados.",
        epilog="Exemplo: procfit run OL_APURACOES_MARCAS --data-ini 2024-01-01 -f xlsx -o saida.xlsx",
    )


def main() -> None:
    """Entry point do CLI."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", newline="")
            except Exception:
                pass

    # Injeta o DynamicRunCommand (Click) no grupo Typer
    click_app = get_command(app)
    click_app.add_command(_make_run_command(), "run")  # type: ignore[union-attr]
    try:
        click_app()
    except Exception as e:
        if type(e).__name__ in ("Exit", "Abort"):
            code = getattr(e, "code", None)
            if code is None:
                code = e.args[0] if e.args and isinstance(e.args[0], int) else 0
            sys.exit(code)
        raise


if __name__ == "__main__":
    main()
