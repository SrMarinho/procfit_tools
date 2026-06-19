"""Renderização de saída no terminal (consoles Rich + métricas + preview).

Responsabilidade única: formatar resultados para o usuário. Não conhece
casos de uso nem infraestrutura.
"""
from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()
err_console = Console(stderr=True)

PREVIEW_LIMIT = 100


def human_size(n: int) -> str:
    """Formata bytes em B/KB/MB/GB."""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def render_metricas(
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
        t.add_row("Tamanho", human_size(tamanho))
    t.add_row("Vazão", f"{vazao:.0f} linhas/s")
    dest.print(t)


def render_preview(table: Any, tempo_consulta: float) -> None:
    total = table.num_rows
    rich_t = Table(header_style="bold cyan")
    for col in table.column_names:
        rich_t.add_column(str(col))
    preview = table.slice(0, PREVIEW_LIMIT)
    cols = [preview.column(i).to_pylist() for i in range(preview.num_columns)]
    for i in range(preview.num_rows):
        rich_t.add_row(*["" if cols[c][i] is None else str(cols[c][i]) for c in range(len(cols))])
    console.print(rich_t)
    if total > PREVIEW_LIMIT:
        console.print(
            f"[dim]... e mais {total - PREVIEW_LIMIT} linhas. "
            f"Use -o para exportar tudo.[/]"
        )
    render_metricas(
        console, linhas=total, colunas=table.num_columns, tempo_consulta=tempo_consulta
    )
