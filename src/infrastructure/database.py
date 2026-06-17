"""Implementação concreta dos repositórios e executor usando ConnectorX + SQL Server.

Padrões:
- Repository: SqlServerQueryRepo, SqlServerParamRepo
- Adapter: ConnectorXExecutor (adapta connectorx às interfaces do domínio)
- Factory: os repositórios são construídos com DbConfig injetado
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import connectorx as cx
import pyarrow as pa
from sqlalchemy import text as sa_text
from sqlalchemy.dialects import mssql as sa_mssql

from src.domain.entities import QueryParametro, SqlQuery
from src.domain.interfaces import ParametroRepository, QueryExecutor, QueryRepository
from src.infrastructure.config import DbConfig

logger = logging.getLogger(__name__)

# Nome de consulta válido: identificador de catálogo (letras, dígitos, _ . - espaço).
# Bloqueia aspas, ponto-e-vírgula, comentários — defesa em profundidade contra injection.
_SAFE_NAME = re.compile(r"^[\w.\- ]+$")


def _sql_literal(value: str) -> str:
    """Escapa um valor como literal de string T-SQL (aspas simples dobradas).

    No SQL Server o único escape em literal de string é dobrar a aspa simples;
    não há escape por backslash. Isso torna o valor um literal inerte.
    """
    return "'" + value.replace("'", "''") + "'"


def _assert_safe_name(nome: str) -> None:
    """Valida o nome da consulta antes de interpolá-lo no SQL."""
    if not nome or not _SAFE_NAME.match(nome):
        raise ValueError(f"Nome de consulta inválido: {nome!r}")


class SqlServerQueryRepo(QueryRepository):
    """
    Repository implementation para CONSULTAS (PBS_NAZARIA_DADOS_DEVELOPER).
    Usa ConnectorX com Arrow Fetch para ler os metadados.
    """

    def __init__(self, config: DbConfig) -> None:
        self._cfg = config

    def listar(
        self, filtro_nome: str | None = None, filtro_desc: str | None = None
    ) -> list[SqlQuery]:
        # Nome + descrição (varchar, leve). O corpo SQL (ntext) é pesado e a
        # listagem não precisa dele (use `buscar`/`show` para o SQL).
        col_id, col_desc = self._cfg.col_id, self._cfg.col_desc
        parts = [f"SELECT {col_id}, {col_desc} FROM CONSULTAS"]
        # Padrões LIKE do SQL Server (curinga %); literais escapados p/ injection.
        # Case-insensitive segue a collation do banco. Ambos → AND.
        conds = []
        if filtro_nome:
            conds.append(f"{col_id} LIKE {_sql_literal(filtro_nome)}")
        if filtro_desc:
            conds.append(f"{col_desc} LIKE {_sql_literal(filtro_desc)}")
        if conds:
            parts.append("WHERE " + " AND ".join(conds))
        if self._cfg.where_extra:
            parts.append(self._cfg.where_extra)
        parts.append(f"ORDER BY {col_id}")
        query = " ".join(parts)

        logger.debug("Listando consultas: %s", query)
        table = cx.read_sql(self._cfg.conn_dados, query, return_type="arrow")

        results: list[SqlQuery] = []
        for row in table.to_pylist():
            nome = str(row[self._cfg.col_id])
            descricao = str(row.get(self._cfg.col_desc, "") or "")
            results.append(SqlQuery(nome=nome, sql="", descricao=descricao))
        return results

    def buscar(self, nome: str) -> Optional[SqlQuery]:
        _assert_safe_name(nome)
        col_id = self._cfg.col_id
        col_query = self._cfg.col_query
        col_desc = self._cfg.col_desc
        # ConnectorX não suporta bind params no MSSQL; usamos literal escapado.
        query = (
            f"SELECT {col_id}, {col_query}, {col_desc} "
            f"FROM CONSULTAS WHERE {col_id} = {_sql_literal(nome)}"
        )

        logger.debug("Buscando consulta: %s", query)
        try:
            table = cx.read_sql(self._cfg.conn_dados, query, return_type="arrow")
        except Exception as exc:
            logger.warning("Erro ao buscar consulta '%s': %s", nome, exc)
            return None

        rows = table.to_pylist()
        if not rows:
            return None

        row = rows[0]
        return SqlQuery(
            nome=str(row[col_id]),
            sql=str(row.get(col_query, "") or ""),
            descricao=str(row.get(col_desc, "") or ""),
        )

    def buscar_sql(self, nome: str) -> Optional[str]:
        """Otimização: retorna só o SQL sem construir o objeto SqlQuery."""
        query = self.buscar(nome)
        return query.sql if query else None


class SqlServerParamRepo(ParametroRepository):
    """
    Repository implementation para CONSULTAS_PARAMS (PBS_NAZARIA_DICIONARIO_DEVELOPER).
    """

    def __init__(self, config: DbConfig) -> None:
        self._cfg = config

    def listar_por_consulta(self, nome_consulta: str) -> list[QueryParametro]:
        _assert_safe_name(nome_consulta)
        query = (
            "SELECT CONSULTA, ORDEM, PARAMETRO, TITULO, TAMANHO, LOOKUP "
            "FROM CONSULTAS_PARAMS "
            f"WHERE CONSULTA = {_sql_literal(nome_consulta)} "
            "ORDER BY ORDEM"
        )

        logger.debug("Buscando parâmetros: %s", query)
        try:
            table = cx.read_sql(self._cfg.conn_dicionario, query, return_type="arrow")
        except Exception as exc:
            logger.warning("Erro ao buscar parâmetros de '%s': %s", nome_consulta, exc)
            return []

        params: list[QueryParametro] = []
        for row in table.to_pylist():
            params.append(QueryParametro(
                nome=str(row["PARAMETRO"]),
                ordem=int(row["ORDEM"]),
                titulo=str(row.get("TITULO", "") or ""),
                tamanho=_safe_int(row.get("TAMANHO")),
                lookup=_safe_str(row.get("LOOKUP")),
            ))
        return params


class ConnectorXExecutor(QueryExecutor):
    """
    Executa SQL no SQL Server via ConnectorX com Arrow Fetch.

    Padrão: Adapter — adapta a biblioteca connectorx à interface QueryExecutor.
    """

    def __init__(self, config: DbConfig) -> None:
        self._cfg = config

    def montar_sql(self, sql: str, params: dict[str, str]) -> str:
        """Retorna o SQL final com os parâmetros substituídos (sem executar)."""
        return self._substituir(sql, params)

    def executar(self, sql: str, params: dict[str, str]) -> pa.Table:
        """Substitui placeholders :PARAM por valores escapados e executa."""
        final_sql = self.montar_sql(sql, params)
        logger.debug("Executando SQL: %s", final_sql[:200])
        table = cx.read_sql(self._cfg.conn_dados, final_sql, return_type="arrow")
        return table

    # Dialeto SQL Server usado só para compilar o bind em literal (sem conexão).
    _DIALECT = sa_mssql.dialect()  # type: ignore[no-untyped-call]

    @classmethod
    def _substituir(cls, sql: str, params: dict[str, str]) -> str:
        """
        Faz o bind dos parâmetros e renderiza o SQL final como string literal.

        Usa SQLAlchemy apenas como compilador (sem engine/conexão): cada
        placeholder :PARAMETRO é trocado por um literal escapado pelo dialeto
        SQL Server (type-aware, aspas simples dobradas) — imune a SQL injection.
        A string resultante é entregue ao connectorx, preservando a performance
        do connectorx com a segurança do bind nomeado.

        Regras:
        - :PARAMETRO presente no SQL mas não fornecido → string vazia
          (semântica 'Vazio=Todos' do Procfit).
        - Variáveis T-SQL (@var) NÃO são placeholders — passam intactas.
        - Um valor que contenha texto de outro placeholder não é reinterpretado:
          o render do literal é final, sem nova varredura.
        """
        stmt = sa_text(sql)
        needed = set(stmt._bindparams.keys())  # nomes :PARAM detectados pelo SQLAlchemy
        if not needed:
            return sql
        binds = {nome: params.get(nome, "") for nome in needed}
        compiled = stmt.bindparams(**binds).compile(
            dialect=cls._DIALECT,
            compile_kwargs={"literal_binds": True},
        )
        return str(compiled)


# --- Helpers ---

def _safe_int(value: object) -> int | None:
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _safe_str(value: object) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s and s.upper() != "NONE" else None