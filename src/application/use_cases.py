"""Casos de uso da aplicação — orquestração do fluxo.

Padrão: Use Case / Command. Cada caso de uso encapsula uma operação
completa do sistema, orquestrando as camadas inferiores (domínio + infra)
sem expor detalhes de implementação.
Segue o SRP (Single Responsibility Principle): cada use case faz uma coisa.
"""
from __future__ import annotations

import time
from pathlib import Path

from src.application.dto import (
    ConsultaDetalheDto,
    ConsultaDto,
    ParametroDto,
    ResultadoDto,
)
from src.domain.enums import ExportFormato
from src.domain.interfaces import Exporter, ParametroRepository, QueryExecutor, QueryRepository


class ListarConsultasUseCase:
    """
    Lista as consultas (nome + descrição), com filtro LIKE opcional.
    DIP: depende da abstração QueryRepository.
    """

    def __init__(self, repo: QueryRepository) -> None:
        self._repo = repo

    def execute(
        self, filtro_nome: str | None = None, filtro_desc: str | None = None
    ) -> list[ConsultaDto]:
        consultas = self._repo.listar(filtro_nome, filtro_desc)
        return [ConsultaDto(nome=c.nome, descricao=c.descricao) for c in consultas]


class DescreverConsultaUseCase:
    """
    Detalhes completos de uma consulta + seus parâmetros.
    """

    def __init__(self, repo: QueryRepository, param_repo: ParametroRepository) -> None:
        self._repo = repo
        self._param_repo = param_repo

    def execute(self, nome: str) -> ConsultaDetalheDto | None:
        query = self._repo.buscar(nome)
        if query is None:
            return None

        params_db = sorted(self._param_repo.listar_por_consulta(nome), key=lambda p: p.ordem)
        params_dto = [
            ParametroDto(
                nome=p.nome,
                flag=p.flag_name,
                titulo=p.titulo or p.nome,
                ordem=p.ordem,
                obrigatorio=p.is_required,
                lookup=p.lookup,
            )
            for p in params_db
        ]
        return ConsultaDetalheDto(
            nome=query.nome,
            sql=query.sql,
            descricao=query.descricao,
            parametros=params_dto,
        )


class ExecutarConsultaUseCase:
    """
    Executa uma consulta com parâmetros e exporta o resultado via streaming.
    DIP: injetam-se as abstrações (QueryRepository, QueryExecutor, Exporter).
    Padrão: Strategy para os exporters (CSV vs XLSX intercambiáveis).
    """

    def __init__(
        self,
        repo: QueryRepository,
        param_repo: ParametroRepository,
        executor: QueryExecutor,
        exporters: dict[ExportFormato, Exporter],
    ) -> None:
        self._repo = repo
        self._param_repo = param_repo
        self._executor = executor
        self._exporters = exporters

    def _preparar(self, nome: str, valores: dict[str, str]) -> str:
        """Busca o SQL e valida os parâmetros obrigatórios. Retorna o SQL bruto."""
        sql = self._repo.buscar_sql(nome)
        if sql is None:
            raise ValueError(f"Consulta '{nome}' não encontrada")

        params_db = self._param_repo.listar_por_consulta(nome)
        for p in params_db:
            if p.is_required and p.nome not in valores:
                raise ValueError(f"Parâmetro obrigatório '{p.nome}' não fornecido")
        return sql

    def gerar_sql(self, nome: str, valores: dict[str, str]) -> str:
        """Monta o SQL final com os parâmetros substituídos, sem executar.

        Não valida obrigatórios (é inspeção): parâmetros omitidos viram ''.
        """
        sql = self._repo.buscar_sql(nome)
        if sql is None:
            raise ValueError(f"Consulta '{nome}' não encontrada")
        return self._executor.montar_sql(sql, valores)

    def execute(
        self,
        nome: str,
        valores: dict[str, str],
        formato: ExportFormato,
        output: Path,
    ) -> ResultadoDto:
        # 1-2. Buscar consulta + validar obrigatórios
        sql = self._preparar(nome, valores)

        # 3. Executar
        t0 = time.perf_counter()
        table = self._executor.executar(sql, valores)
        t_consulta = time.perf_counter() - t0

        # 4. Exportar (streaming)
        exporter = self._exporters.get(formato)
        if exporter is None:
            raise ValueError(f"Exportador para formato '{formato.value}' não configurado")

        t1 = time.perf_counter()
        linhas = exporter.exportar(table, output)
        t_export = time.perf_counter() - t1

        tamanho = output.stat().st_size if output.exists() else 0
        return ResultadoDto(
            arquivo=str(output),
            linhas=linhas,
            tempo_segundos=round(t_consulta + t_export, 2),
            formato=formato.value,
            colunas=table.num_columns,
            tempo_consulta=round(t_consulta, 2),
            tempo_export=round(t_export, 2),
            tamanho_bytes=tamanho,
        )