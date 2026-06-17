"""Testes unitários — ParameterRepository + QueryRepository com mocks.

Usa unittest.mock para simular o connectorx, testando isoladamente
a lógica dos repositórios sem depender de banco real.
"""
from __future__ import annotations

import pytest

from src.domain.entities import QueryParametro, SqlQuery
from src.infrastructure.config import DbConfig
from src.infrastructure.database import (
    SqlServerParamRepo,
    SqlServerQueryRepo,
    ConnectorXExecutor,
)


# ═══════════════════════════════════════════════════════════════════
# Tests: SqlServerQueryRepo
# ═══════════════════════════════════════════════════════════════════

class TestSqlServerQueryRepo:
    """Testa o repositório de CONSULTAS com connectorx mockado."""

    def test_listar_retorna_lista(self, mocker):
        """Deve retornar uma lista de SqlQuery a partir do Arrow Table."""
        import pyarrow as pa

        mock_table = pa.table({
            "CONSULTA": ["Q1", "Q2"],
            "DESCRICAO": ["Desc 1", "Desc 2"],
        })
        mocker.patch("connectorx.read_sql", return_value=mock_table)

        config = DbConfig(host="mock", user="u", password="p")
        repo = SqlServerQueryRepo(config)
        result = repo.listar()

        assert len(result) == 2
        assert result[0].nome == "Q1"
        assert result[0].descricao == "Desc 1"
        assert result[0].sql == ""  # listar() não traz o corpo SQL
        assert isinstance(result[1], SqlQuery)

    def test_listar_com_filtro_usa_like(self, mocker):
        """Filtro deve virar cláusula LIKE no SQL (curinga preservado)."""
        import pyarrow as pa

        m = mocker.patch(
            "connectorx.read_sql",
            return_value=pa.table({"CONSULTA": ["B2B_X"], "DESCRICAO": ["d"]}),
        )
        repo = SqlServerQueryRepo(DbConfig(host="m", user="u", password="p"))
        result = repo.listar("B2B%")

        assert len(result) == 1
        sql_arg = m.call_args[0][1]  # 2º posicional = query
        assert "LIKE 'B2B%'" in sql_arg

    def test_listar_filtra_nome_e_descricao_com_and(self, mocker):
        """Ambos filtros → cláusula AND sobre nome e descrição."""
        import pyarrow as pa

        m = mocker.patch(
            "connectorx.read_sql",
            return_value=pa.table({"CONSULTA": ["B2B_X"], "DESCRICAO": ["cliente"]}),
        )
        repo = SqlServerQueryRepo(DbConfig(host="m", user="u", password="p"))
        repo.listar("B2B%", "%cliente%")

        sql_arg = m.call_args[0][1]
        assert "CONSULTA LIKE 'B2B%'" in sql_arg
        assert "DESCRICAO LIKE '%cliente%'" in sql_arg
        assert " AND " in sql_arg

    def test_buscar_inexistente_retorna_none(self, mocker):
        """Deve retornar None quando a consulta não existe."""
        import pyarrow as pa

        mock_table = pa.table({"CONSULTA": [], "QUERY": []})
        mocker.patch("connectorx.read_sql", return_value=mock_table)

        config = DbConfig(host="mock", user="u", password="p")
        repo = SqlServerQueryRepo(config)
        result = repo.buscar("NAO_EXISTE")

        assert result is None


# ═══════════════════════════════════════════════════════════════════
# Tests: SqlServerParamRepo
# ═══════════════════════════════════════════════════════════════════

class TestSqlServerParamRepo:
    """Testa o repositório de CONSULTAS_PARAMS com connectorx mockado."""

    def test_listar_por_consulta(self, mocker):
        """Deve retornar QueryParametro ordenado por ORDEM."""
        import pyarrow as pa

        mock_table = pa.table({
            "CONSULTA": ["Q1", "Q1"],
            "ORDEM": [10, 20],
            "PARAMETRO": ["DATA_INI", "EMPRESA"],
            "TITULO": ["Data Inicial", "Empresa"],
            "TAMANHO": [15, 15],
            "LOOKUP": ["DATA", None],
        })
        mocker.patch("connectorx.read_sql", return_value=mock_table)

        config = DbConfig(host="mock", user="u", password="p")
        repo = SqlServerParamRepo(config)
        result = repo.listar_por_consulta("Q1")

        assert len(result) == 2
        assert result[0].nome == "DATA_INI"
        assert result[0].flag_name == "data-ini"
        assert result[0].lookup == "DATA"
        assert result[1].lookup is None

    def test_consulta_sem_parametros_retorna_vazio(self, mocker):
        """Deve retornar lista vazia quando não há parâmetros."""
        import pyarrow as pa

        mock_table = pa.table({
            "CONSULTA": [],
            "ORDEM": [],
            "PARAMETRO": [],
            "TITULO": [],
            "TAMANHO": [],
            "LOOKUP": [],
        })
        mocker.patch("connectorx.read_sql", return_value=mock_table)

        config = DbConfig(host="mock", user="u", password="p")
        repo = SqlServerParamRepo(config)
        result = repo.listar_por_consulta("SEM_PARAMS")

        assert result == []


# ═══════════════════════════════════════════════════════════════════
# Tests: ConnectorXExecutor
# ═══════════════════════════════════════════════════════════════════

class TestSubstituir:
    """Testa a substituição de placeholders no SQL."""

    def test_substitui_dois_pontos(self):
        """:PARAM deve ser substituído pelo valor escapado."""
        sql = "SELECT * FROM VENDAS WHERE data BETWEEN :DATA_INI AND :DATA_FIM"
        params = {"DATA_INI": "2024-01-01", "DATA_FIM": "2024-12-31"}
        result = ConnectorXExecutor._substituir(sql, params)
        assert "2024-01-01" in result
        assert "2024-12-31" in result
        assert ":DATA_INI" not in result

    def test_escapa_aspas_simples(self):
        """Aspas simples nos valores devem ser escapadas."""
        sql = "SELECT * FROM CLIENTES WHERE nome = :NOME"
        params = {"NOME": "O'Brien"}
        result = ConnectorXExecutor._substituir(sql, params)
        assert "O''Brien" in result

    def test_sem_parametros_nao_altera(self):
        """SQL sem placeholders deve permanecer igual."""
        sql = "SELECT * FROM VENDAS"
        result = ConnectorXExecutor._substituir(sql, {})
        assert result == "SELECT * FROM VENDAS"

    def test_arroba_nao_e_substituido(self):
        """@VAR é variável nativa do T-SQL — deve ser preservada."""
        sql = "DECLARE @ID INT; SELECT * FROM T WHERE id = @ID AND d = :DATA"
        result = ConnectorXExecutor._substituir(sql, {"ID": "42", "DATA": "2024-01-01"})
        assert "@ID" in result  # variável T-SQL intacta
        assert "d = '2024-01-01'" in result  # placeholder :DATA substituído

    def test_injection_no_valor_vira_literal_inerte(self):
        """Payload de injection no valor deve virar literal escapado, não SQL."""
        sql = "SELECT * FROM CLIENTES WHERE nome = :NOME"
        params = {"NOME": "'; DROP TABLE CLIENTES; --"}
        result = ConnectorXExecutor._substituir(sql, params)
        assert result == (
            "SELECT * FROM CLIENTES WHERE nome = '''; DROP TABLE CLIENTES; --'"
        )
        assert "DROP TABLE" in result  # presente, mas dentro do literal

    def test_valor_com_nome_de_outro_placeholder_nao_re_substitui(self):
        """Single-pass: valor contendo :OUTRO não dispara re-substituição."""
        sql = "WHERE a = :A AND b = :B"
        params = {"A": "x:B", "B": "y"}
        result = ConnectorXExecutor._substituir(sql, params)
        # :A vira 'x:B' (literal), o :B de dentro do valor NÃO é tocado
        assert result == "WHERE a = 'x:B' AND b = 'y'"

    def test_placeholder_nao_fornecido_vira_vazio(self):
        """Placeholder no SQL sem valor → string vazia (semântica Vazio=Todos)."""
        sql = "WHERE a = :A AND b = :B"
        result = ConnectorXExecutor._substituir(sql, {"A": "1"})
        assert result == "WHERE a = '1' AND b = ''"


class TestSafeName:
    """Valida o bloqueio de nomes de consulta perigosos."""

    def test_nome_valido_passa(self, mocker):
        import pyarrow as pa

        mocker.patch("connectorx.read_sql", return_value=pa.table({"CONSULTA": [], "QUERY": []}))
        repo = SqlServerQueryRepo(DbConfig(host="m", user="u", password="p"))
        assert repo.buscar("OL_APURACOES_MARCAS") is None  # não levanta

    def test_nome_com_aspa_e_rejeitado(self):
        repo = SqlServerQueryRepo(DbConfig(host="m", user="u", password="p"))
        with pytest.raises(ValueError, match="inválido"):
            repo.buscar("x'; DROP TABLE CONSULTAS; --")

    def test_param_repo_rejeita_nome_perigoso(self):
        repo = SqlServerParamRepo(DbConfig(host="m", user="u", password="p"))
        with pytest.raises(ValueError, match="inválido"):
            repo.listar_por_consulta("a';--")


# ═══════════════════════════════════════════════════════════════════
# Tests: QueryParametro (domínio)
# ═══════════════════════════════════════════════════════════════════

class TestQueryParametro:
    """Testa regras de negócio do QueryParametro."""

    def test_flag_name_converte_underscore_para_hifen(self):
        p = QueryParametro(nome="DATA_INI", ordem=10, titulo="Data Inicial")
        assert p.flag_name == "data-ini"

    def test_flag_name_sem_underscore(self):
        p = QueryParametro(nome="TIPO", ordem=10, titulo="Tipo")
        assert p.flag_name == "tipo"

    def test_is_required_true_com_asterisco(self):
        p = QueryParametro(nome="EMPRESA", ordem=10, titulo="Empresa *")
        assert p.is_required is True

    def test_is_required_false_sem_asterisco(self):
        p = QueryParametro(nome="MARCA", ordem=10, titulo="Marcas (Vazio=Todas)")
        assert p.is_required is False

    def test_is_required_false_titulo_simples(self):
        p = QueryParametro(nome="TIPO", ordem=10, titulo="Tipo")
        assert p.is_required is False