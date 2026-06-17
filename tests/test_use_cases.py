"""Testes dos casos de uso com mocks.

Testa a orquestração (use cases) isoladamente, mockando os repositórios.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pyarrow as pa
import pytest

from src.application.use_cases import (
    DescreverConsultaUseCase,
    ExecutarConsultaUseCase,
    ListarConsultasUseCase,
)
from src.domain.entities import QueryParametro, SqlQuery
from src.domain.enums import ExportFormato
from src.domain.interfaces import Exporter


@pytest.fixture
def mock_query_repo():
    repo = MagicMock()
    repo.listar.return_value = [
        SqlQuery(nome="CONSULTA_A", sql="SELECT 1", descricao="Desc A"),
        SqlQuery(nome="CONSULTA_B", sql="SELECT 2 WHERE x = :PARAM", descricao="Desc B"),
    ]
    repo.buscar.return_value = SqlQuery(nome="CONSULTA_A", sql="SELECT 1", descricao="Desc A")
    repo.buscar_sql.return_value = "SELECT 1 WHERE data BETWEEN :DATA_INI AND :DATA_FIM"
    return repo


@pytest.fixture
def mock_param_repo():
    repo = MagicMock()
    repo.listar_por_consulta.return_value = [
        QueryParametro(nome="DATA_INI", ordem=10, titulo="Data Inicial", lookup="DATA"),
        QueryParametro(nome="DATA_FIM", ordem=20, titulo="Data Final"),
        QueryParametro(nome="MARCA", ordem=30, titulo="Marcas (Vazio=Todas)"),
    ]
    return repo


@pytest.fixture
def mock_executor():
    executor = MagicMock()
    executor.executar.return_value = pa.table({
        "col1": [1, 2, 3],
        "col2": ["a", "b", "c"],
    })
    executor.montar_sql.return_value = "SELECT 1 WHERE data BETWEEN '2024-01-01' AND '2024-12-31'"
    return executor


@pytest.fixture
def mock_exporter():
    exporter = MagicMock(spec=Exporter)
    exporter.exportar.return_value = 3
    return exporter


# ═══════════════════════════════════════════════════════════════════
# Tests: ListarConsultasUseCase
# ═══════════════════════════════════════════════════════════════════

class TestListarConsultasUseCase:
    """Deve listar consultas com contagem de parâmetros."""

    def test_execute_retorna_lista(self, mock_query_repo):
        uc = ListarConsultasUseCase(mock_query_repo)
        result = uc.execute()
        assert len(result) == 2
        assert result[0].nome == "CONSULTA_A"
        assert result[0].descricao == "Desc A"

    def test_execute_repassa_filtros(self, mock_query_repo):
        uc = ListarConsultasUseCase(mock_query_repo)
        uc.execute("B2B%", "%cliente%")
        mock_query_repo.listar.assert_called_once_with("B2B%", "%cliente%")


# ═══════════════════════════════════════════════════════════════════
# Tests: DescreverConsultaUseCase
# ═══════════════════════════════════════════════════════════════════

class TestDescreverConsultaUseCase:
    """Deve mostrar detalhes de uma consulta."""

    def test_execute_retorna_detalhes(self, mock_query_repo, mock_param_repo):
        uc = DescreverConsultaUseCase(mock_query_repo, mock_param_repo)
        result = uc.execute("CONSULTA_A")
        assert result is not None
        assert result.nome == "CONSULTA_A"
        assert result.sql == "SELECT 1"
        assert len(result.parametros) == 3
        assert result.parametros[0].flag == "data-ini"
        assert result.parametros[0].obrigatorio is True  # DATA_INI não tem vazio=todas
        assert result.parametros[2].obrigatorio is False  # MARCA tem

    def test_execute_consulta_inexistente(self, mock_query_repo, mock_param_repo):
        mock_query_repo.buscar.return_value = None
        uc = DescreverConsultaUseCase(mock_query_repo, mock_param_repo)
        result = uc.execute("NAO_EXISTE")
        assert result is None


# ═══════════════════════════════════════════════════════════════════
# Tests: ExecutarConsultaUseCase
# ═══════════════════════════════════════════════════════════════════

class TestExecutarConsultaUseCase:
    """Deve executar e exportar."""

    def test_execute_sucesso(self, mock_query_repo, mock_param_repo,
                             mock_executor, mock_exporter):
        exporters = {ExportFormato.CSV: mock_exporter}
        uc = ExecutarConsultaUseCase(
            mock_query_repo, mock_param_repo,
            mock_executor, exporters,
        )

        result = uc.execute(
            nome="CONSULTA_A",
            valores={"DATA_INI": "2024-01-01", "DATA_FIM": "2024-12-31"},
            formato=ExportFormato.CSV,
            output=Path("teste.csv"),
        )

        assert result.linhas == 3
        assert result.formato == "csv"
        mock_executor.executar.assert_called_once()
        mock_exporter.exportar.assert_called_once()

    def test_execute_param_obrigatorio_faltando(self, mock_query_repo, mock_param_repo,
                                                 mock_executor, mock_exporter):
        exporters = {ExportFormato.CSV: mock_exporter}
        uc = ExecutarConsultaUseCase(
            mock_query_repo, mock_param_repo,
            mock_executor, exporters,
        )

        with pytest.raises(ValueError, match="DATA_INI"):
            uc.execute(
                nome="CONSULTA_A",
                valores={"DATA_FIM": "2024-12-31"},  # FALTA DATA_INI
                formato=ExportFormato.CSV,
                output=Path("teste.csv"),
            )

    def test_gerar_sql_nao_executa(self, mock_query_repo, mock_param_repo,
                                   mock_executor, mock_exporter):
        uc = ExecutarConsultaUseCase(
            mock_query_repo, mock_param_repo,
            mock_executor, {ExportFormato.CSV: mock_exporter},
        )

        sql = uc.gerar_sql(
            "CONSULTA_A",
            {"DATA_INI": "2024-01-01", "DATA_FIM": "2024-12-31"},
        )

        assert sql == "SELECT 1 WHERE data BETWEEN '2024-01-01' AND '2024-12-31'"
        mock_executor.montar_sql.assert_called_once()
        mock_executor.executar.assert_not_called()  # dry-run não executa
        mock_exporter.exportar.assert_not_called()

    def test_gerar_sql_nao_valida_obrigatorio(self, mock_query_repo, mock_param_repo,
                                              mock_executor, mock_exporter):
        """Dry-run é inspeção: gera o SQL mesmo sem os parâmetros obrigatórios."""
        uc = ExecutarConsultaUseCase(
            mock_query_repo, mock_param_repo,
            mock_executor, {ExportFormato.CSV: mock_exporter},
        )

        sql = uc.gerar_sql("CONSULTA_A", {})  # sem nenhum param
        assert sql  # não levanta
        mock_executor.montar_sql.assert_called_once()