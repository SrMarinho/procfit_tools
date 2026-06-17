"""Testes dos exportadores com dados reais em memória.

Testa a exportação CSV e XLSX para arquivos temporários.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pyarrow as pa
import pytest

from src.infrastructure.exporters import CsvExporter, XlsxExporter


@pytest.fixture
def sample_table() -> pa.Table:
    return pa.table({
        "nome": ["Ana", "Bruno", "Carla"],
        "valor": [100.0, 200.0, 300.0],
        "ativo": [True, False, True],
    })


class TestCsvExporter:
    """Testa exportação CSV."""

    def test_exporta_csv_com_cabecalho_e_dados(self, sample_table, tmp_path):
        output = tmp_path / "teste.csv"
        exporter = CsvExporter(delimiter=";")
        linhas = exporter.exportar(sample_table, output)

        assert linhas == 3
        content = output.read_text(encoding="utf-8-sig")
        assert "nome;valor;ativo" in content
        assert "Bruno" in content

    def test_exporta_csv_vazio(self, tmp_path):
        table = pa.table({"a": [], "b": []})
        output = tmp_path / "vazio.csv"
        exporter = CsvExporter()
        linhas = exporter.exportar(table, output)

        assert linhas == 0
        content = output.read_text()
        assert "a;b" in content  # só cabeçalho (delimiter padrão = ;)


class TestXlsxExporter:
    """Testa exportação XLSX."""

    def test_exporta_xlsx_com_dados(self, sample_table, tmp_path):
        output = tmp_path / "teste.xlsx"
        exporter = XlsxExporter(sheet_name="Dados")
        linhas = exporter.exportar(sample_table, output)

        assert linhas == 3
        assert output.exists()
        assert output.stat().st_size > 0

    def test_exporta_xlsx_vazio(self, tmp_path):
        table = pa.table({"a": [], "b": []})
        output = tmp_path / "vazio.xlsx"
        exporter = XlsxExporter()
        linhas = exporter.exportar(table, output)

        assert linhas == 0
        assert output.exists()