"""Interfaces (ports) da arquitetura hexagonal / layered.

Cada interface define um CONTRATO que o domínio espera da infraestrutura.
A infra implementa essas interfaces; o domínio (use cases) depende apenas
destas abstrações — DIP (Dependency Inversion Principle).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import pyarrow as pa

from procfit.domain.entities import QueryCampo, QueryParametro, SqlQuery


class QueryRepository(ABC):
    """
    Acesso à tabela CONSULTAS (PBS_NAZARIA_DADOS_DEVELOPER).
    Padrão: Repository.
    """

    @abstractmethod
    def listar(
        self, filtro_nome: str | None = None, filtro_desc: str | None = None
    ) -> list[SqlQuery]:
        """Retorna as consultas disponíveis.

        `filtro_nome` e `filtro_desc` são padrões LIKE do SQL Server (use `%`
        como curinga), aplicados a CONSULTA e DESCRICAO respectivamente.
        Quando ambos são informados, combinam com AND. None/"" não filtra.
        """
        ...

    @abstractmethod
    def buscar(self, nome: str) -> SqlQuery | None:
        """Busca uma consulta pelo nome. Retorna None se não existir."""
        ...

    @abstractmethod
    def buscar_sql(self, nome: str) -> str | None:
        """Retorna apenas o SQL bruto da consulta."""
        ...


class ParametroRepository(ABC):
    """
    Acesso à tabela CONSULTAS_PARAMS (PBS_NAZARIA_DICIONARIO_DEVELOPER).
    Padrão: Repository.
    """

    @abstractmethod
    def listar_por_consulta(self, nome_consulta: str) -> list[QueryParametro]:
        """Retorna os parâmetros de uma consulta, ordenados por ORDEM."""
        ...


class CampoRepository(ABC):
    """Acesso à tabela CONSULTAS_CAMPOS (PBS_NAZARIA_DICIONARIO_DEVELOPER)."""

    @abstractmethod
    def listar_por_consulta(self, nome_consulta: str) -> list[QueryCampo]:
        """Retorna as colunas de saída de uma consulta, ordenadas por ORDEM."""
        ...


class QueryExecutor(ABC):
    """
    Execução de SQL no SQL Server via ConnectorX com Arrow Fetch.
    Padrão: Strategy / Executor.
    """

    @abstractmethod
    def montar_sql(self, sql: str, params: dict[str, str]) -> str:
        """Substitui os placeholders e retorna o SQL final, sem executar."""
        ...

    @abstractmethod
    def executar(self, sql: str, params: dict[str, str]) -> pa.Table:
        """
        Substitui placeholders no SQL e executa.
        Retorna pyarrow.Table (zero-copy, ideal para streaming).
        """
        ...


class Exporter(ABC):
    """
    Exportação de pyarrow.Table para arquivo em disco.
    Padrão: Strategy — permite diferentes formatos intercambiáveis.
    """

    @abstractmethod
    def exportar(self, table: pa.Table, output: Path) -> int:
        """
        Exporta a tabela para o arquivo.
        Retorna o número de linhas exportadas.
        Deve usar streaming (write sem carregar tudo na RAM).
        """
        ...