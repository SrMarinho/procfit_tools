"""Exportadores que implementam a interface Exporter.

Padrão: Strategy. Cada formato (CSV, XLSX) é uma estratégia intercambiável.
Ambos usam streaming (write sem carregar tudo na RAM).
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import TextIO

import pyarrow as pa

from procfit.domain.interfaces import Exporter


class CsvExporter(Exporter):
    """
    Exporta pyarrow.Table para CSV com streaming.

    Usa o módulo `csv` da stdlib para escrita linha a linha.
    O PyArrow Table é iterado por batches (lazy), e cada batch é escrito
    imediatamente — nunca materializa o dataset inteiro.
    """

    def __init__(self, delimiter: str = ";") -> None:
        self._delimiter = delimiter

    def exportar(self, table: pa.Table, output: Path, include_header: bool = True) -> int:
        with open(output, "w", newline="", encoding="utf-8-sig") as f:
            return self.exportar_stream(table, f, include_header=include_header)

    def exportar_stream(self, table: pa.Table, f: TextIO, include_header: bool = True) -> int:
        total = 0
        writer = csv.writer(f, delimiter=self._delimiter)

        if include_header:
            writer.writerow(table.column_names)

        # Streaming por batches
        for batch in table.to_batches():
            for row in batch.to_pylist():
                writer.writerow(list(row.values()))
                total += 1

        return total


class XlsxExporter(Exporter):
    """
    Exporta pyarrow.Table para XLSX com streaming (write_only).

    Usa openpyxl em modo write_only=True, que escreve diretamente no ZIP
    sem manter as linhas em memória. Ideal para datasets grandes.
    """

    def __init__(self, sheet_name: str = "Dados") -> None:
        self._sheet_name = sheet_name

    def exportar(self, table: pa.Table, output: Path) -> int:
        from openpyxl import Workbook

        wb = Workbook(write_only=True)
        ws = wb.create_sheet(title=self._sheet_name)

        # Cabeçalho
        ws.append(list(table.column_names))

        # Streaming por batches
        total = 0
        for batch in table.to_batches():
            for row in batch.to_pylist():
                ws.append(list(row.values()))
                total += 1

        wb.save(output)
        return total