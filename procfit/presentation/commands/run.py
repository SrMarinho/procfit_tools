"""Comando `run` — Click puro com parâmetros dinâmicos vindos do banco.

DynamicRunCommand injeta as opções da consulta em parse_args (lidas do banco
em thread com timeout). A lógica de invoke é fatiada em helpers coesos para
evitar um método-deus.
"""
from __future__ import annotations

import itertools
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

import click
import pyarrow as pa

from procfit.application.use_cases import ExecutarConsultaUseCase
from procfit.domain.enums import ExportFormato
from procfit.infrastructure.config import ExportConfig
from procfit.infrastructure.database import SqlServerParamRepo
from procfit.infrastructure.exporters import CsvExporter, XlsxExporter
from procfit.presentation.concurrency import run_interruptible
from procfit.presentation.container import Components
from procfit.presentation.rendering import console, err_console, render_metricas, render_preview

logger = logging.getLogger(__name__)

# Opções fixas do comando (não são parâmetros de consulta).
_FIXAS = ("consulta", "format", "output", "verbose", "force", "dry_run", "stdout", "no_header")


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

    # ── injeção de opções dinâmicas ──────────────────────────────────
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
            self.params.append(click.Option(
                param_decls=[f"--{opt_name}"],
                help=p.titulo or p.nome,
                default=(),
                type=str,
                multiple=True,
                required=False,
                expose_value=True,
            ))

    @staticmethod
    def _extract_consulta(args: list[str]) -> Optional[str]:
        for arg in args:
            if not arg.startswith("-"):
                return arg
        return None

    # ── execução ─────────────────────────────────────────────────────
    def invoke(self, ctx: click.Context) -> Any:
        consulta = ctx.params.get("consulta", "")
        if not consulta:
            err_console.print("[bold red]✖ Nome da consulta é obrigatório.[/]")
            sys.exit(1)

        if ctx.params.get("verbose", False):
            logging.getLogger().setLevel(logging.DEBUG)

        assert self._run_uc is not None
        run_uc = self._run_uc
        valores_base, valores_multi = self._split_params(ctx)
        combos = self._build_combos(valores_base, valores_multi)

        if ctx.params.get("dry_run", False):
            return self._do_dry_run(run_uc, consulta, combos, valores_multi)

        try:
            formato = ExportFormato.from_str(ctx.params.get("format", "csv"))
        except ValueError as e:
            err_console.print(f"[bold red]✖[/] {e}")
            sys.exit(2)

        stdout_flag = ctx.params.get("stdout", False)
        table, t_consulta = self._execute_all(run_uc, consulta, combos, valores_multi, stdout_flag)
        self._output(ctx, table, t_consulta, formato, stdout_flag)

    @staticmethod
    def _split_params(ctx: click.Context) -> tuple[dict[str, str], dict[str, list[str]]]:
        """Separa params dinâmicos em valor único e multi-valor (tupla > 1)."""
        valores_base: dict[str, str] = {}
        valores_multi: dict[str, list[str]] = {}
        for key, value in ctx.params.items():
            if key in _FIXAS:
                continue
            if isinstance(value, tuple):
                if len(value) == 1:
                    valores_base[key.upper()] = value[0]
                elif len(value) > 1:
                    valores_multi[key.upper()] = list(value)
            elif value is not None:
                valores_base[key.upper()] = str(value)
        return valores_base, valores_multi

    @staticmethod
    def _build_combos(
        base: dict[str, str], multi: dict[str, list[str]]
    ) -> list[dict[str, str]]:
        """Produto cartesiano dos params multi-valor sobre a base."""
        if not multi:
            return [base]
        keys = list(multi.keys())
        return [
            {**base, **dict(zip(keys, combo))}
            for combo in itertools.product(*[multi[k] for k in keys])
        ]

    @staticmethod
    def _do_dry_run(
        run_uc: ExecutarConsultaUseCase,
        consulta: str,
        combos: list[dict[str, str]],
        valores_multi: dict[str, list[str]],
    ) -> None:
        n = len(combos)
        for i, valores in enumerate(combos):
            if n > 1:
                desc = ", ".join(f"{k}={v}" for k, v in valores.items() if k in valores_multi)
                print(f"-- [{i + 1}/{n}] {desc}")
            try:
                print(run_uc.gerar_sql(consulta, valores))
            except ValueError as e:
                err_console.print(f"[bold red]✖[/] {e}")
                sys.exit(2)

    def _execute_all(
        self,
        run_uc: ExecutarConsultaUseCase,
        consulta: str,
        combos: list[dict[str, str]],
        valores_multi: dict[str, list[str]],
        stdout_flag: bool,
    ) -> tuple[pa.Table, float]:
        try:
            descricao = run_uc.obter_descricao(consulta)
        except Exception:
            descricao = ""
        rotulo = f"[cyan]{consulta}[/]" + (f" — {descricao}" if descricao else "")
        n = len(combos)
        dest = err_console if stdout_flag else console

        try:
            tables: list[pa.Table] = []
            total_t = 0.0
            for i, valores in enumerate(combos):
                label = f"Executando {rotulo} ({i + 1}/{n})..." if n > 1 else f"Executando {rotulo}..."
                with dest.status(label):
                    t, elapsed = run_interruptible(
                        lambda v=valores: run_uc.executar_tabela(consulta, v)
                    )
                tables.append(t)
                total_t += elapsed
            table = pa.concat_tables(tables) if len(tables) > 1 else tables[0]
            return table, total_t
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

    def _output(
        self,
        ctx: click.Context,
        table: pa.Table,
        t_consulta: float,
        formato: ExportFormato,
        stdout_flag: bool,
    ) -> None:
        no_header = ctx.params.get("no_header", False)
        output_str: str | None = ctx.params.get("output")
        force = ctx.params.get("force", False)
        export_cfg = ExportConfig()

        if stdout_flag:
            if formato is ExportFormato.XLSX:
                err_console.print("[bold red]✖ XLSX é binário; --stdout só suporta csv.[/]")
                sys.exit(2)
            exporter = CsvExporter(export_cfg.csv_delimiter)
            linhas = exporter.exportar_stream(table, sys.stdout, include_header=not no_header)
            render_metricas(err_console, linhas=linhas, colunas=table.num_columns, tempo_consulta=t_consulta)
            return

        if output_str:
            self._export_file(table, t_consulta, formato, output_str, force, no_header, export_cfg)
            return

        render_preview(table, t_consulta)

    @staticmethod
    def _export_file(
        table: pa.Table,
        t_consulta: float,
        formato: ExportFormato,
        output_str: str,
        force: bool,
        no_header: bool,
        export_cfg: ExportConfig,
    ) -> None:
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
                linhas = CsvExporter(export_cfg.csv_delimiter).exportar(
                    table, output, include_header=not no_header
                )
            else:
                linhas = XlsxExporter(export_cfg.xlsx_sheet_name).exportar(table, output)
            t_export = round(time.perf_counter() - t1, 2)
        except OSError as e:
            err_console.print(f"[bold red]✖ Erro ao escrever arquivo:[/] {e}")
            logger.exception("Falha na escrita")
            sys.exit(4)
        tamanho = output.stat().st_size if output.exists() else 0
        console.print(f"[bold green]✔ Concluído![/] {output}")
        render_metricas(
            console, linhas=linhas, colunas=table.num_columns,
            tempo_consulta=t_consulta, tempo_export=t_export,
            tempo_total=round(t_consulta + t_export, 2), tamanho=tamanho,
        )


def build_run_command() -> click.Command:
    """Factory do comando run com dependências injetadas."""
    components = Components()
    return DynamicRunCommand(
        name="run",
        param_repo=components.param_repo,
        run_uc=components.executar_uc(),
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
